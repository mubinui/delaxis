"""ChromaDB backend.

Chroma keeps documents, metadata and vectors together and persists to a
directory, so this is a thin adapter: the work is mapping Chroma's distances
back to the similarity scores the rest of the system speaks.
"""

from __future__ import annotations

from typing import Any

from src.rag.stores.base import Record, SearchHit, VectorStoreError


def _client(path: str, host: str | None, port: int | None):
    try:
        import chromadb
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise VectorStoreError(
            "the chromadb backend needs the 'chromadb' package: pip install chromadb"
        ) from exc
    if host:
        return chromadb.HttpClient(host=host, port=port or 8000)
    return chromadb.PersistentClient(path=path)


class ChromaVectorStore:
    """Vectors in ChromaDB, local directory or remote server."""

    name = "chromadb"

    def __init__(
        self,
        persist_directory: str = "./data/chromadb",
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        self._client = _client(persist_directory, host, port)

    def _collection(self, collection: str, create: bool = True):
        if create:
            # Cosine, to match every other backend here. Chroma defaults to L2,
            # which would make scores from this store incomparable with the rest.
            return self._client.get_or_create_collection(
                collection, metadata={"hnsw:space": "cosine"}
            )
        try:
            return self._client.get_collection(collection)
        except Exception:
            return None

    def upsert(self, collection: str, records: list[Record]) -> int:
        if not records:
            return 0
        handle = self._collection(collection)
        handle.upsert(
            ids=[record.id for record in records],
            documents=[record.text for record in records],
            embeddings=[record.embedding for record in records],
            metadatas=[record.metadata or {"source": ""} for record in records],
        )
        return len(records)

    def search(
        self,
        collection: str,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        handle = self._collection(collection, create=False)
        if handle is None:
            return []
        result = handle.query(
            query_embeddings=[embedding],
            n_results=max(1, top_k),
            where=where or None,
        )
        hits: list[SearchHit] = []
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        for index, identifier in enumerate(ids):
            distance = distances[index] if index < len(distances) else 0.0
            hits.append(SearchHit(
                id=identifier,
                text=documents[index] if index < len(documents) else "",
                # Chroma reports cosine *distance*; the rest of this system
                # ranks on similarity, where larger is better.
                score=1.0 - float(distance),
                metadata=dict(metadatas[index] or {}) if index < len(metadatas) else {},
            ))
        return hits

    def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
    ) -> int:
        handle = self._collection(collection, create=False)
        if handle is None:
            return 0
        before = handle.count()
        if ids:
            handle.delete(ids=ids)
        elif where:
            handle.delete(where=where)
        else:
            self._client.delete_collection(collection)
            return before
        return max(0, before - handle.count())

    def drop(self, collection: str) -> bool:
        try:
            self._client.delete_collection(collection)
            return True
        except Exception:
            return False

    def collections(self) -> list[str]:
        return sorted(item.name for item in self._client.list_collections())

    def stats(self, collection: str) -> dict[str, Any]:
        handle = self._collection(collection, create=False)
        if handle is None:
            return {"collection": collection, "chunks": 0, "documents": 0,
                    "dimensions": 0, "characters": 0, "backend": self.name}
        rows = handle.get(include=["metadatas", "documents"])
        documents = rows.get("documents") or []
        metadatas = rows.get("metadatas") or []
        return {
            "collection": collection,
            "chunks": handle.count(),
            "documents": len({(item or {}).get("source", "") for item in metadatas}),
            "dimensions": 0,
            "characters": sum(len(text or "") for text in documents),
            "backend": self.name,
        }

    def sources(self, collection: str) -> list[dict[str, Any]]:
        handle = self._collection(collection, create=False)
        if handle is None:
            return []
        rows = handle.get(include=["metadatas", "documents"])
        grouped: dict[str, dict[str, Any]] = {}
        documents = rows.get("documents") or []
        for index, metadata in enumerate(rows.get("metadatas") or []):
            source = (metadata or {}).get("source", "")
            entry = grouped.setdefault(
                source, {"source": source, "chunks": 0, "characters": 0, "ingested_at": None}
            )
            entry["chunks"] += 1
            if index < len(documents):
                entry["characters"] += len(documents[index] or "")
        return sorted(grouped.values(), key=lambda item: item["source"])
