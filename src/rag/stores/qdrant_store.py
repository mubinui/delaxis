"""Qdrant backend.

Runs three ways from the same adapter: against a server, against a local
directory, or entirely in memory. The in-memory mode is what the tests use, so
this backend is exercised for real rather than mocked.

Qdrant wants point ids to be integers or UUIDs, and this system addresses chunks
by readable string ids, so ids are hashed to UUIDs on the way in and the
original is carried in the payload.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.rag.stores.base import Record, SearchHit, VectorStoreError, matches

#: Fixed namespace, so the same chunk id always maps to the same point id — an
#: upsert has to replace the point it replaced last time.
_NAMESPACE = uuid.UUID("6f1a1d1e-2b7c-4c1a-9f39-6d2a0c5f3b21")


def _modules():
    try:
        from qdrant_client import QdrantClient, models
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise VectorStoreError(
            "the qdrant backend needs the 'qdrant-client' package: pip install qdrant-client"
        ) from exc
    return QdrantClient, models


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, chunk_id))


class QdrantVectorStore:
    """Vectors in Qdrant: server, local path, or in memory."""

    name = "qdrant"

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        path: str | None = None,
        prefer_grpc: bool = False,
        timeout: int = 60,
    ) -> None:
        client_class, models = _modules()
        self._models = models
        if url:
            self._client = client_class(
                url=url, api_key=api_key, prefer_grpc=prefer_grpc, timeout=timeout
            )
        else:
            # ":memory:" is a supported path and needs no server.
            self._client = client_class(path=path or ":memory:")

    def _ensure(self, collection: str, dimensions: int) -> None:
        if self._client.collection_exists(collection):
            return
        self._client.create_collection(
            collection_name=collection,
            vectors_config=self._models.VectorParams(
                size=dimensions, distance=self._models.Distance.COSINE
            ),
        )

    def upsert(self, collection: str, records: list[Record]) -> int:
        if not records:
            return 0
        self._ensure(collection, len(records[0].embedding))
        points = [
            self._models.PointStruct(
                id=_point_id(record.id),
                vector=list(record.embedding),
                payload={
                    "chunk_id": record.id,
                    "text": record.text,
                    "metadata": record.metadata,
                    # Lifted out of metadata so it can be filtered server-side.
                    "source": record.metadata.get("source", ""),
                },
            )
            for record in records
        ]
        self._client.upsert(collection_name=collection, points=points, wait=True)
        return len(points)

    def search(
        self,
        collection: str,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        if not self._client.collection_exists(collection):
            return []

        query_filter = None
        leftover = dict(where or {})
        if "source" in leftover:
            # Filtering in the database beats over-fetching and discarding.
            query_filter = self._models.Filter(must=[
                self._models.FieldCondition(
                    key="source",
                    match=self._models.MatchValue(value=leftover.pop("source")),
                )
            ])

        found = self._client.query_points(
            collection_name=collection,
            query=list(embedding),
            limit=max(1, top_k) * (4 if leftover else 1),
            query_filter=query_filter,
            with_payload=True,
        ).points

        hits: list[SearchHit] = []
        for point in found:
            payload = point.payload or {}
            metadata = payload.get("metadata") or {}
            if not matches(metadata, leftover):
                continue
            hits.append(SearchHit(
                id=payload.get("chunk_id", str(point.id)),
                text=payload.get("text", ""),
                score=float(point.score),
                metadata=metadata,
            ))
            if len(hits) >= top_k:
                break
        return hits

    def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
    ) -> int:
        if not self._client.collection_exists(collection):
            return 0
        before = self.stats(collection)["chunks"]

        if ids:
            self._client.delete(
                collection_name=collection,
                points_selector=self._models.PointIdsList(
                    points=[_point_id(chunk_id) for chunk_id in ids]
                ),
                wait=True,
            )
        elif where and set(where) == {"source"}:
            self._client.delete(
                collection_name=collection,
                points_selector=self._models.FilterSelector(
                    filter=self._models.Filter(must=[
                        self._models.FieldCondition(
                            key="source",
                            match=self._models.MatchValue(value=where["source"]),
                        )
                    ])
                ),
                wait=True,
            )
        elif where:
            doomed = [
                point.payload["chunk_id"]
                for point in self._scroll(collection)
                if matches((point.payload or {}).get("metadata") or {}, where)
            ]
            if not doomed:
                return 0
            return self.delete(collection, ids=doomed)
        else:
            self._client.delete_collection(collection)
            return before

        return max(0, before - self.stats(collection)["chunks"])

    def drop(self, collection: str) -> bool:
        if not self._client.collection_exists(collection):
            return False
        self._client.delete_collection(collection)
        return True

    def _scroll(self, collection: str):
        points, cursor = self._client.scroll(
            collection_name=collection, limit=512, with_payload=True
        )
        while points:
            yield from points
            if cursor is None:
                return
            points, cursor = self._client.scroll(
                collection_name=collection, limit=512, offset=cursor, with_payload=True
            )

    def collections(self) -> list[str]:
        return sorted(item.name for item in self._client.get_collections().collections)

    def stats(self, collection: str) -> dict[str, Any]:
        if not self._client.collection_exists(collection):
            return {"collection": collection, "chunks": 0, "documents": 0,
                    "dimensions": 0, "characters": 0, "backend": self.name}
        info = self._client.get_collection(collection)
        sources = self.sources(collection)
        vectors = info.config.params.vectors
        return {
            "collection": collection,
            "chunks": info.points_count or 0,
            "documents": len(sources),
            "dimensions": getattr(vectors, "size", 0),
            "characters": sum(item["characters"] for item in sources),
            "backend": self.name,
        }

    def sources(self, collection: str) -> list[dict[str, Any]]:
        if not self._client.collection_exists(collection):
            return []
        grouped: dict[str, dict[str, Any]] = {}
        for point in self._scroll(collection):
            payload = point.payload or {}
            source = payload.get("source", "")
            entry = grouped.setdefault(
                source, {"source": source, "chunks": 0, "characters": 0, "ingested_at": None}
            )
            entry["chunks"] += 1
            entry["characters"] += len(payload.get("text", ""))
        return sorted(grouped.values(), key=lambda item: item["source"])
