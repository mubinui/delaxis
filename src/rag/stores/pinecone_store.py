"""Pinecone backend.

Collections map to Pinecone *namespaces* inside one index, not to one index
each. Indexes are slow to create, are billed individually, and on the serverless
tier there is a hard cap on how many an account may have — so a system that
makes a collection per uploaded document would stop working after a few dozen
files. Namespaces are free, instant, and isolate queries exactly as needed.

Pinecone metadata is flat: strings, numbers, booleans and lists of strings.
Anything nested is JSON-encoded on the way in and decoded on the way out, so
callers keep the same metadata contract as every other backend.
"""

from __future__ import annotations

import json
import time
from typing import Any

from src.rag.stores.base import Record, SearchHit, VectorStoreError

#: Metadata key holding the chunk text. Pinecone allows 40 KB of metadata per
#: vector, comfortably more than a chunk.
_TEXT = "_text"
#: Metadata key holding the JSON-encoded original metadata.
_EXTRA = "_metadata"


def _pinecone():
    try:
        from pinecone import Pinecone, ServerlessSpec
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise VectorStoreError(
            "the pinecone backend needs the 'pinecone' package: pip install pinecone"
        ) from exc
    return Pinecone, ServerlessSpec


def _flatten(metadata: dict[str, Any]) -> dict[str, Any]:
    """Pinecone-safe metadata, with the original carried alongside."""
    flat: dict[str, Any] = {_EXTRA: json.dumps(metadata, default=str)}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            flat[key] = value
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            flat[key] = value
    return flat


def _restore(flat: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    text = flat.get(_TEXT, "")
    try:
        metadata = json.loads(flat.get(_EXTRA) or "{}")
    except (TypeError, ValueError):
        metadata = {key: value for key, value in flat.items() if not key.startswith("_")}
    return text, metadata


class PineconeVectorStore:
    """Vectors in Pinecone; one index, a namespace per collection."""

    name = "pinecone"

    def __init__(
        self,
        api_key: str,
        index_name: str = "delaxis",
        dimensions: int = 1536,
        cloud: str = "aws",
        region: str = "us-east-1",
    ) -> None:
        client_class, spec_class = _pinecone()
        if not api_key:
            raise VectorStoreError("the pinecone backend needs an API key")
        self._client = client_class(api_key=api_key)
        self._spec = spec_class(cloud=cloud, region=region)
        self._index_name = index_name
        self._dimensions = dimensions
        self._index = None

    def _handle(self):
        if self._index is not None:
            return self._index
        existing = {item["name"] for item in self._client.list_indexes()}
        if self._index_name not in existing:
            self._client.create_index(
                name=self._index_name,
                dimension=self._dimensions,
                metric="cosine",
                spec=self._spec,
            )
            # A new serverless index is not queryable the instant it is created.
            for _ in range(60):
                if self._client.describe_index(self._index_name).status.get("ready"):
                    break
                time.sleep(1.0)
        self._index = self._client.Index(self._index_name)
        return self._index

    def upsert(self, collection: str, records: list[Record]) -> int:
        if not records:
            return 0
        vectors = [
            {
                "id": record.id,
                "values": list(record.embedding),
                "metadata": {**_flatten(record.metadata), _TEXT: record.text},
            }
            for record in records
        ]
        handle = self._handle()
        # Batched: Pinecone caps a single upsert request by size, and a few
        # hundred chunks of a long PDF will exceed it.
        for start in range(0, len(vectors), 100):
            handle.upsert(vectors=vectors[start:start + 100], namespace=collection)
        return len(vectors)

    def search(
        self,
        collection: str,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        response = self._handle().query(
            vector=list(embedding),
            top_k=max(1, top_k),
            namespace=collection,
            include_metadata=True,
            filter={key: {"$eq": value} for key, value in (where or {}).items()} or None,
        )
        hits: list[SearchHit] = []
        for match in response.get("matches", []):
            text, metadata = _restore(match.get("metadata") or {})
            hits.append(SearchHit(
                id=match["id"], text=text, score=float(match.get("score", 0.0)),
                metadata=metadata,
            ))
        return hits

    def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
    ) -> int:
        handle = self._handle()
        before = self.stats(collection)["chunks"]
        if ids:
            handle.delete(ids=list(ids), namespace=collection)
        elif where:
            handle.delete(
                filter={key: {"$eq": value} for key, value in where.items()},
                namespace=collection,
            )
        else:
            handle.delete(delete_all=True, namespace=collection)
            return before
        return max(0, before - self.stats(collection)["chunks"])

    def drop(self, collection: str) -> bool:
        try:
            self._handle().delete(delete_all=True, namespace=collection)
            return True
        except Exception:
            return False

    def collections(self) -> list[str]:
        stats = self._handle().describe_index_stats()
        return sorted(stats.get("namespaces", {}))

    def stats(self, collection: str) -> dict[str, Any]:
        stats = self._handle().describe_index_stats()
        namespace = (stats.get("namespaces", {}) or {}).get(collection, {})
        return {
            "collection": collection,
            "chunks": int(namespace.get("vector_count", 0)),
            # Pinecone reports counts, not contents; listing every vector to
            # group them by source would cost a full scan on every call.
            "documents": 0,
            "dimensions": int(stats.get("dimension", self._dimensions)),
            "characters": 0,
            "backend": self.name,
        }

    def sources(self, collection: str) -> list[dict[str, Any]]:
        handle = self._handle()
        grouped: dict[str, dict[str, Any]] = {}
        try:
            for page in handle.list(namespace=collection):
                fetched = handle.fetch(ids=list(page), namespace=collection)
                for vector in (fetched.get("vectors") or {}).values():
                    text, metadata = _restore(vector.get("metadata") or {})
                    source = metadata.get("source", "")
                    entry = grouped.setdefault(
                        source,
                        {"source": source, "chunks": 0, "characters": 0, "ingested_at": None},
                    )
                    entry["chunks"] += 1
                    entry["characters"] += len(text)
        except Exception as exc:  # listing is not available on every tier
            raise VectorStoreError(f"could not list documents in Pinecone: {exc}") from exc
        return sorted(grouped.values(), key=lambda item: item["source"])
