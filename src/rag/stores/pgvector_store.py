"""PostgreSQL + pgvector backend.

Written against raw SQL through psycopg2, which the project already depends on,
rather than pulling in an ORM layer or the ``pgvector`` helper package. The
extension does the distance calculation, so ordering and limiting happen in the
database instead of in Python.

One table holds every collection, partitioned by a column rather than by table,
because creating a table per collection turns collection names into DDL and
makes them a much sharper injection surface.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from src.rag.stores.base import Record, SearchHit, VectorStoreError, matches


def _psycopg():
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor, execute_values
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise VectorStoreError(
            "the pgvector backend needs 'psycopg2-binary': pip install psycopg2-binary"
        ) from exc
    return psycopg2, RealDictCursor, execute_values


def _literal(vector: list[float]) -> str:
    """pgvector's text input format."""
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


class PgVectorStore:
    """Vectors in PostgreSQL, distances computed by pgvector."""

    name = "pgvector"

    def __init__(
        self,
        connection_string: str,
        table_name: str = "rag_embeddings",
        vector_dimensions: int = 768,
    ) -> None:
        self._psycopg, self._cursor_factory, self._execute_values = _psycopg()
        self._dsn = connection_string
        # Interpolated into DDL, so it is restricted to an identifier rather
        # than trusted. Collections are a column; only this is ever DDL.
        if not table_name.replace("_", "").isalnum():
            raise VectorStoreError(f"unsafe table name {table_name!r}")
        self._table = table_name
        self._dimensions = vector_dimensions
        self._lock = threading.Lock()
        self._ready = False

    def _connect(self):
        try:
            return self._psycopg.connect(self._dsn)
        except Exception as exc:
            raise VectorStoreError(f"could not connect to PostgreSQL: {exc}") from exc

    def _ensure(self) -> None:
        if self._ready:
            return
        with self._lock, self._connect() as connection, connection.cursor() as cursor:
            try:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            except Exception as exc:
                raise VectorStoreError(
                    "the 'vector' extension is not installed and could not be created. "
                    "Run CREATE EXTENSION vector as a superuser, or use the pgvector "
                    f"Docker image. ({exc})"
                ) from exc
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table} ("
                " id TEXT NOT NULL,"
                " collection TEXT NOT NULL,"
                " source TEXT NOT NULL DEFAULT '',"
                " text TEXT NOT NULL,"
                f" embedding vector({self._dimensions}) NOT NULL,"
                " metadata JSONB NOT NULL DEFAULT '{}'::jsonb,"
                " created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
                " PRIMARY KEY (collection, id))"
            )
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS {self._table}_collection_idx "
                f"ON {self._table} (collection, source)"
            )
            connection.commit()
        self._ready = True

    def upsert(self, collection: str, records: list[Record]) -> int:
        if not records:
            return 0
        self._ensure()
        rows = [
            (record.id, collection, record.metadata.get("source", ""), record.text,
             _literal(record.embedding), json.dumps(record.metadata, default=str))
            for record in records
        ]
        with self._connect() as connection, connection.cursor() as cursor:
            self._execute_values(
                cursor,
                f"INSERT INTO {self._table} "
                "(id, collection, source, text, embedding, metadata) VALUES %s "
                "ON CONFLICT (collection, id) DO UPDATE SET "
                "source = EXCLUDED.source, text = EXCLUDED.text, "
                "embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata",
                rows,
            )
            connection.commit()
        return len(rows)

    def search(
        self,
        collection: str,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        self._ensure()
        clauses = ["collection = %s"]
        params: list[Any] = [collection]
        leftover = dict(where or {})
        if "source" in leftover:
            clauses.append("source = %s")
            params.append(leftover.pop("source"))
        if leftover:
            # Everything else goes through JSONB containment, still server-side.
            clauses.append("metadata @> %s::jsonb")
            params.append(json.dumps(leftover))

        # The vector is bound twice — once to compute the score, once to order by
        # it — and psycopg2 has no named parameters, so the order here has to
        # match the order the placeholders appear in the statement.
        vector = _literal(embedding)
        statement = (
            f"SELECT id, text, metadata, 1 - (embedding <=> %s::vector) AS score "
            f"FROM {self._table} WHERE {' AND '.join(clauses)} "
            f"ORDER BY embedding <=> %s::vector LIMIT %s"
        )
        with self._connect() as connection, \
                connection.cursor(cursor_factory=self._cursor_factory) as cursor:
            cursor.execute(statement, [vector, *params, vector, max(1, top_k)])
            rows = cursor.fetchall()

        return [
            SearchHit(id=row["id"], text=row["text"], score=float(row["score"]),
                      metadata=row["metadata"] or {})
            for row in rows
        ]

    def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
    ) -> int:
        self._ensure()
        clauses = ["collection = %s"]
        params: list[Any] = [collection]
        if ids:
            clauses.append("id = ANY(%s)")
            params.append(list(ids))
        elif where:
            leftover = dict(where)
            if "source" in leftover:
                clauses.append("source = %s")
                params.append(leftover.pop("source"))
            if leftover:
                clauses.append("metadata @> %s::jsonb")
                params.append(json.dumps(leftover))

        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {self._table} WHERE {' AND '.join(clauses)}", params)
            removed = cursor.rowcount
            connection.commit()
        return max(0, removed)

    def drop(self, collection: str) -> bool:
        return self.delete(collection) > 0

    def collections(self) -> list[str]:
        self._ensure()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT DISTINCT collection FROM {self._table} ORDER BY collection")
            return [row[0] for row in cursor.fetchall()]

    def stats(self, collection: str) -> dict[str, Any]:
        self._ensure()
        with self._connect() as connection, \
                connection.cursor(cursor_factory=self._cursor_factory) as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS chunks, COUNT(DISTINCT source) AS documents, "
                "COALESCE(SUM(LENGTH(text)), 0) AS characters "
                f"FROM {self._table} WHERE collection = %s",
                (collection,),
            )
            row = cursor.fetchone() or {}
        return {
            "collection": collection,
            "chunks": int(row.get("chunks", 0)),
            "documents": int(row.get("documents", 0)),
            "dimensions": self._dimensions,
            "characters": int(row.get("characters", 0)),
            "backend": self.name,
        }

    def sources(self, collection: str) -> list[dict[str, Any]]:
        self._ensure()
        with self._connect() as connection, \
                connection.cursor(cursor_factory=self._cursor_factory) as cursor:
            cursor.execute(
                "SELECT source, COUNT(*) AS chunks, COALESCE(SUM(LENGTH(text)), 0) AS characters, "
                "MIN(created_at) AS ingested_at "
                f"FROM {self._table} WHERE collection = %s GROUP BY source ORDER BY source",
                (collection,),
            )
            return [
                {"source": row["source"], "chunks": int(row["chunks"]),
                 "characters": int(row["characters"]),
                 "ingested_at": row["ingested_at"].isoformat() if row["ingested_at"] else None}
                for row in cursor.fetchall()
            ]
