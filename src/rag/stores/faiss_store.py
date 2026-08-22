"""FAISS backend.

FAISS stores vectors and nothing else — no text, no metadata, no collection
names — so this keeps a sidecar JSON file alongside each index holding what
FAISS will not. That is the whole reason this file is longer than the others.

Vectors are L2-normalised on the way in and searched with inner product, which
is cosine similarity, so scores are comparable with every other backend here.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import numpy as np

from src.rag.stores.base import Record, SearchHit, VectorStoreError, matches


def _faiss():
    try:
        import faiss
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise VectorStoreError(
            "the faiss backend needs the 'faiss-cpu' package: pip install faiss-cpu"
        ) from exc
    return faiss


def _unit(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class FaissVectorStore:
    """Vectors in FAISS, with the text and metadata kept beside the index."""

    name = "faiss"

    def __init__(self, path: str = "./data/faiss") -> None:
        self._faiss = _faiss()
        self._root = Path(path)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # collection -> (index, {id: {text, metadata}}, [id in row order])
        self._loaded: dict[str, tuple[Any, dict[str, Any], list[str]]] = {}

    # -- persistence -------------------------------------------------------- #

    def _paths(self, collection: str) -> tuple[Path, Path]:
        return self._root / f"{collection}.faiss", self._root / f"{collection}.json"

    def _load(self, collection: str, dimensions: int | None = None):
        if collection in self._loaded:
            return self._loaded[collection]

        index_path, sidecar_path = self._paths(collection)
        if index_path.exists() and sidecar_path.exists():
            index = self._faiss.read_index(str(index_path))
            sidecar = json.loads(sidecar_path.read_text())
            entry = (index, sidecar["records"], sidecar["order"])
        elif dimensions:
            # IDMap2 so records can be removed by id; a bare flat index can only
            # be rebuilt from scratch after a delete.
            index = self._faiss.IndexIDMap2(self._faiss.IndexFlatIP(dimensions))
            entry = (index, {}, [])
        else:
            return None

        self._loaded[collection] = entry
        return entry

    def _save(self, collection: str) -> None:
        entry = self._loaded.get(collection)
        if entry is None:
            return
        index, records, order = entry
        index_path, sidecar_path = self._paths(collection)
        self._faiss.write_index(index, str(index_path))
        sidecar_path.write_text(json.dumps({"records": records, "order": order}))

    # -- writing ------------------------------------------------------------ #

    def upsert(self, collection: str, records: list[Record]) -> int:
        if not records:
            return 0
        vectors = _unit(np.asarray([record.embedding for record in records], dtype=np.float32))

        with self._lock:
            entry = self._load(collection, dimensions=vectors.shape[1])
            index, stored, order = entry

            # Replacing means removing first: FAISS would otherwise hold both
            # copies and return the stale one as a separate hit.
            replacing = [record.id for record in records if record.id in stored]
            if replacing:
                index.remove_ids(np.asarray([order.index(rid) for rid in replacing], dtype=np.int64))

            row_ids = []
            for record in records:
                if record.id in stored:
                    row_ids.append(order.index(record.id))
                else:
                    order.append(record.id)
                    row_ids.append(len(order) - 1)
                stored[record.id] = {"text": record.text, "metadata": record.metadata}

            index.add_with_ids(vectors, np.asarray(row_ids, dtype=np.int64))
            self._save(collection)
        return len(records)

    def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
    ) -> int:
        with self._lock:
            entry = self._load(collection)
            if entry is None:
                return 0
            index, stored, order = entry

            if ids:
                doomed = [rid for rid in ids if rid in stored]
            elif where:
                doomed = [rid for rid, row in stored.items() if matches(row["metadata"], where)]
            else:
                doomed = list(stored)

            if not doomed:
                return 0
            index.remove_ids(np.asarray([order.index(rid) for rid in doomed], dtype=np.int64))
            for rid in doomed:
                stored.pop(rid, None)
            self._save(collection)
            return len(doomed)

    def drop(self, collection: str) -> bool:
        with self._lock:
            index_path, sidecar_path = self._paths(collection)
            existed = index_path.exists()
            index_path.unlink(missing_ok=True)
            sidecar_path.unlink(missing_ok=True)
            self._loaded.pop(collection, None)
            return existed

    # -- reading ------------------------------------------------------------ #

    def search(
        self,
        collection: str,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        entry = self._load(collection)
        if entry is None:
            return []
        index, stored, order = entry
        if not stored:
            return []

        query = _unit(np.asarray([embedding], dtype=np.float32))
        if query.shape[1] != index.d:
            raise VectorStoreError(
                f"collection {collection!r} holds {index.d}-dimension vectors but the query "
                f"is {query.shape[1]}. The embedding provider changed — re-ingest or switch back."
            )

        # Over-fetch when filtering, since matches are decided after the search.
        want = max(1, top_k) * (6 if where else 1)
        scores, rows = index.search(query, min(want, max(1, len(stored))))

        hits: list[SearchHit] = []
        for score, row in zip(scores[0], rows[0]):
            if row < 0 or row >= len(order):
                continue
            rid = order[int(row)]
            record = stored.get(rid)
            if record is None or not matches(record["metadata"], where):
                continue
            hits.append(SearchHit(id=rid, text=record["text"],
                                  score=float(score), metadata=record["metadata"]))
            if len(hits) >= top_k:
                break
        return hits

    def collections(self) -> list[str]:
        return sorted(path.stem for path in self._root.glob("*.faiss"))

    def stats(self, collection: str) -> dict[str, Any]:
        entry = self._load(collection)
        if entry is None:
            return {"collection": collection, "chunks": 0, "documents": 0,
                    "dimensions": 0, "characters": 0, "backend": self.name}
        index, stored, _ = entry
        return {
            "collection": collection,
            "chunks": len(stored),
            "documents": len({row["metadata"].get("source", "") for row in stored.values()}),
            "dimensions": index.d,
            "characters": sum(len(row["text"]) for row in stored.values()),
            "backend": self.name,
        }

    def sources(self, collection: str) -> list[dict[str, Any]]:
        entry = self._load(collection)
        if entry is None:
            return []
        grouped: dict[str, dict[str, Any]] = {}
        for row in entry[1].values():
            source = row["metadata"].get("source", "")
            item = grouped.setdefault(
                source, {"source": source, "chunks": 0, "characters": 0, "ingested_at": None}
            )
            item["chunks"] += 1
            item["characters"] += len(row["text"])
        return sorted(grouped.values(), key=lambda item: item["source"])
