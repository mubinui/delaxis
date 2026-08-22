"""The default vector store: SQLite, on disk, no service to run.

This exists because the previous RAG implementation required a separate
service at ``localhost:8003`` that nothing in the repository started, so every
retrieval tool timed out on a fresh install. Retrieval should work the moment
you upload a file, and adding Qdrant or Pinecone should be an upgrade rather
than the price of entry.

Search is brute force: every vector in the collection is scored against the
query. That is the right choice at this size — an exact scan of fifty thousand
chunks takes a few milliseconds with numpy, and it has no index to build, tune,
rebuild after deletes, or get subtly wrong. The specialised backends exist for
when a collection outgrows it.

Vectors are stored as raw float32 rather than JSON: a third of the bytes and no
parsing on the way back in, which is most of the query cost at this scale.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

import numpy as np

from src.rag.stores.base import Record, SearchHit, VectorStoreError, matches

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_chunks (
    id          TEXT NOT NULL,
    collection  TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT '',
    text        TEXT NOT NULL,
    embedding   BLOB NOT NULL,
    dimensions  INTEGER NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (collection, id)
);
CREATE INDEX IF NOT EXISTS rag_chunks_collection ON rag_chunks (collection);
CREATE INDEX IF NOT EXISTS rag_chunks_source ON rag_chunks (collection, source);
"""


def database_path() -> Path:
    """Where the vectors live, honouring the DELAXIS_DATA_DIR override."""
    default = str(_PROJECT_ROOT / "data")
    data_dir = Path(os.environ.get("DELAXIS_DATA_DIR") or default)
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "rag_vectors.db"


class SqliteVectorStore:
    """Vectors in SQLite, scored in memory."""

    name = "sqlite"

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else database_path()
        if str(self._path) != ":memory:":
            self._path.parent.mkdir(parents=True, exist_ok=True)
        # SQLite serialises writers anyway; holding the lock across read-then-write
        # also keeps an upsert from racing a concurrent delete of the same ids.
        self._lock = threading.Lock()
        self._memory: sqlite3.Connection | None = None
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        if str(self._path) == ":memory:":
            # One shared connection, or each call would get an empty database.
            if self._memory is None:
                self._memory = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory.row_factory = sqlite3.Row
            return self._memory
        connection = sqlite3.connect(str(self._path), timeout=15.0)
        connection.row_factory = sqlite3.Row
        # WAL keeps a query from blocking behind an ingest.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    # -- writing ----------------------------------------------------------- #

    def upsert(self, collection: str, records: list[Record]) -> int:
        if not records:
            return 0
        rows = []
        for record in records:
            vector = np.asarray(record.embedding, dtype=np.float32)
            if vector.ndim != 1 or not vector.size:
                raise VectorStoreError(f"record {record.id!r} has no usable embedding")
            rows.append((
                record.id,
                collection,
                str(record.metadata.get("source", "")),
                record.text,
                vector.tobytes(),
                int(vector.size),
                json.dumps(record.metadata, default=str),
            ))

        with self._lock:
            connection = self._connect()
            try:
                connection.executemany(
                    "INSERT INTO rag_chunks "
                    "(id, collection, source, text, embedding, dimensions, metadata) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(collection, id) DO UPDATE SET "
                    "source=excluded.source, text=excluded.text, "
                    "embedding=excluded.embedding, dimensions=excluded.dimensions, "
                    "metadata=excluded.metadata",
                    rows,
                )
                connection.commit()
            finally:
                self._close(connection)
        return len(rows)

    def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
    ) -> int:
        with self._lock:
            connection = self._connect()
            try:
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    cursor = connection.execute(
                        f"DELETE FROM rag_chunks WHERE collection = ? AND id IN ({placeholders})",
                        [collection, *ids],
                    )
                    removed = cursor.rowcount
                elif where and set(where) == {"source"}:
                    # The common case, and worth doing in SQL rather than by
                    # loading every row to compare one column.
                    cursor = connection.execute(
                        "DELETE FROM rag_chunks WHERE collection = ? AND source = ?",
                        (collection, where["source"]),
                    )
                    removed = cursor.rowcount
                elif where:
                    doomed = [
                        row["id"]
                        for row in connection.execute(
                            "SELECT id, metadata FROM rag_chunks WHERE collection = ?",
                            (collection,),
                        )
                        if matches(json.loads(row["metadata"]), where)
                    ]
                    removed = 0
                    if doomed:
                        placeholders = ",".join("?" for _ in doomed)
                        cursor = connection.execute(
                            f"DELETE FROM rag_chunks WHERE collection = ? AND id IN ({placeholders})",
                            [collection, *doomed],
                        )
                        removed = cursor.rowcount
                else:
                    cursor = connection.execute(
                        "DELETE FROM rag_chunks WHERE collection = ?", (collection,)
                    )
                    removed = cursor.rowcount
                connection.commit()
                return max(0, removed)
            finally:
                self._close(connection)

    def drop(self, collection: str) -> bool:
        return self.delete(collection) > 0

    # -- reading ----------------------------------------------------------- #

    def search(
        self,
        collection: str,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        query = np.asarray(embedding, dtype=np.float32)
        if not query.size:
            return []

        connection = self._connect()
        try:
            if where and set(where) == {"source"}:
                rows = connection.execute(
                    "SELECT id, text, embedding, dimensions, metadata FROM rag_chunks "
                    "WHERE collection = ? AND source = ?",
                    (collection, where["source"]),
                ).fetchall()
                where = None          # already applied
            else:
                rows = connection.execute(
                    "SELECT id, text, embedding, dimensions, metadata FROM rag_chunks "
                    "WHERE collection = ?",
                    (collection,),
                ).fetchall()
        finally:
            self._close(connection)

        if not rows:
            return []

        keep: list[tuple[sqlite3.Row, dict[str, Any], np.ndarray]] = []
        for row in rows:
            metadata = json.loads(row["metadata"])
            if not matches(metadata, where):
                continue
            # A collection embedded with one model and queried with another
            # would otherwise raise deep inside numpy with nothing to act on.
            if row["dimensions"] != query.size:
                raise VectorStoreError(
                    f"collection {collection!r} holds {row['dimensions']}-dimension vectors "
                    f"but the query is {query.size}. The embedding provider changed — "
                    f"re-ingest the collection or switch back."
                )
            keep.append((row, metadata, np.frombuffer(row["embedding"], dtype=np.float32)))

        if not keep:
            return []

        matrix = np.vstack([vector for _, _, vector in keep])
        # Normalise both sides so the dot product is cosine similarity. Some
        # providers return unit vectors and some do not.
        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0] = 1.0
        query_norm = float(np.linalg.norm(query)) or 1.0
        scores = (matrix @ query) / (norms * query_norm)

        top_k = max(1, min(top_k, len(keep)))
        # argpartition finds the top k without sorting everything else.
        best = np.argpartition(-scores, top_k - 1)[:top_k]
        best = best[np.argsort(-scores[best])]

        return [
            SearchHit(
                id=keep[index][0]["id"],
                text=keep[index][0]["text"],
                score=float(scores[index]),
                metadata=keep[index][1],
            )
            for index in best
        ]

    def collections(self) -> list[str]:
        connection = self._connect()
        try:
            return [
                row["collection"]
                for row in connection.execute(
                    "SELECT DISTINCT collection FROM rag_chunks ORDER BY collection"
                )
            ]
        finally:
            self._close(connection)

    def stats(self, collection: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT COUNT(*) AS chunks, COUNT(DISTINCT source) AS sources, "
                "COALESCE(MAX(dimensions), 0) AS dimensions, "
                "COALESCE(SUM(LENGTH(text)), 0) AS characters "
                "FROM rag_chunks WHERE collection = ?",
                (collection,),
            ).fetchone()
        finally:
            self._close(connection)
        return {
            "collection": collection,
            "chunks": row["chunks"],
            "documents": row["sources"],
            "dimensions": row["dimensions"],
            "characters": row["characters"],
            "backend": self.name,
        }

    def sources(self, collection: str) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT source, COUNT(*) AS chunks, SUM(LENGTH(text)) AS characters, "
                "MIN(created_at) AS ingested_at "
                "FROM rag_chunks WHERE collection = ? GROUP BY source ORDER BY source",
                (collection,),
            ).fetchall()
        finally:
            self._close(connection)
        return [
            {
                "source": row["source"],
                "chunks": row["chunks"],
                "characters": row["characters"] or 0,
                "ingested_at": row["ingested_at"],
            }
            for row in rows
        ]

    def _close(self, connection: sqlite3.Connection) -> None:
        # The in-memory database is one long-lived connection; closing it would
        # throw the data away.
        if connection is not self._memory:
            connection.close()
