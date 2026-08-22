"""The retrieval pipeline, assembled.

Ties the three replaceable pieces together — a chunker, an embedding provider
and a vector store — and is the only thing the tools and the HTTP API talk to.
Swapping Pinecone for pgvector, or Gemini embeddings for local ones, changes
what this builds and nothing above it.

Ingestion is idempotent by construction: chunk ids are derived from the source
name and the chunk index, so re-ingesting a file replaces its chunks rather than
duplicating them, and a document that got shorter does not leave orphans behind.
"""

from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from src.rag.chunking import DEFAULT_CHUNK_CHARS, DEFAULT_OVERLAP_CHARS, chunk_text
from src.rag.embeddings import EmbeddingProvider, create_embedder
from src.rag.stores import Record, VectorStore, create_store, normalise_collection

logger = structlog.get_logger(__name__)

DEFAULT_COLLECTION = "knowledge-base"
#: Retrieval below this is noise. Cosine similarity on lexical embeddings is
#: rarely high even for a good match, so this is deliberately permissive; the
#: caller sees the score and can be stricter.
DEFAULT_MIN_SCORE = 0.02


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


@dataclass
class RagConfig:
    """Everything that decides how retrieval behaves."""

    backend: str = field(default_factory=lambda: _env("RAG_BACKEND", "sqlite"))
    embedding_provider: str = field(default_factory=lambda: _env("RAG_EMBEDDING_PROVIDER", "local"))
    embedding_model: str = field(default_factory=lambda: _env("RAG_EMBEDDING_MODEL"))
    embedding_base_url: str = field(default_factory=lambda: _env("RAG_EMBEDDING_BASE_URL"))
    chunk_chars: int = field(
        default_factory=lambda: int(_env("RAG_CHUNK_CHARS", str(DEFAULT_CHUNK_CHARS)))
    )
    overlap_chars: int = field(
        default_factory=lambda: int(_env("RAG_CHUNK_OVERLAP", str(DEFAULT_OVERLAP_CHARS)))
    )
    default_collection: str = field(
        default_factory=lambda: _env("RAG_DEFAULT_COLLECTION", DEFAULT_COLLECTION)
    )

    def fingerprint(self) -> tuple:
        """Identity for caching — a change here means rebuilding the service."""
        return (self.backend, self.embedding_provider, self.embedding_model,
                self.embedding_base_url, self.chunk_chars, self.overlap_chars)


@dataclass
class Ingested:
    """What one ingestion produced."""

    source: str
    collection: str
    chunks: int
    characters: int
    replaced: int = 0
    extractor: str = ""
    note: str = ""


class RagService:
    """Chunk, embed, store, retrieve."""

    def __init__(
        self,
        config: RagConfig | None = None,
        store: VectorStore | None = None,
        embedder: EmbeddingProvider | None = None,
    ) -> None:
        self.config = config or RagConfig()
        self._store = store
        self._embedder = embedder
        self._lock = threading.Lock()

    # -- lazily built, so importing this module never opens a database ------ #

    @property
    def store(self) -> VectorStore:
        if self._store is None:
            with self._lock:
                if self._store is None:
                    self._store = create_store(self.config.backend)
        return self._store

    @property
    def embedder(self) -> EmbeddingProvider:
        if self._embedder is None:
            with self._lock:
                if self._embedder is None:
                    self._embedder = create_embedder(
                        self.config.embedding_provider,
                        model=self.config.embedding_model or None,
                        base_url=self.config.embedding_base_url or None,
                    )
        return self._embedder

    def collection_for(self, collection: str | None) -> str:
        return normalise_collection(collection or self.config.default_collection)

    # -- writing ------------------------------------------------------------ #

    def ingest_text(
        self,
        text: str,
        *,
        source: str,
        collection: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Ingested:
        """Chunk, embed and store one document."""
        name = self.collection_for(collection)
        base = {
            "source": source,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        }

        chunks = chunk_text(
            text,
            chunk_chars=self.config.chunk_chars,
            overlap_chars=self.config.overlap_chars,
            metadata=base,
        )
        if not chunks:
            return Ingested(source=source, collection=name, chunks=0, characters=0,
                            note="nothing to index — the document had no extractable text")

        # Replace the previous version wholesale. Upserting by id would leave
        # the tail of a document that has since become shorter sitting in the
        # index, answering questions from text the file no longer contains.
        replaced = self.store.delete(name, where={"source": source})

        vectors = self.embedder.embed([chunk.text for chunk in chunks])
        records = [
            Record(
                id=self._chunk_id(source, index),
                text=chunk.text,
                embedding=vector,
                metadata={**chunk.metadata, "chunk": index, "chunks": len(chunks)},
            )
            for index, (chunk, vector) in enumerate(zip(chunks, vectors))
        ]
        self.store.upsert(name, records)

        logger.info(
            "rag_ingested", source=source, collection=name,
            chunks=len(records), replaced=replaced, backend=self.store.name,
        )
        return Ingested(
            source=source, collection=name, chunks=len(records),
            characters=sum(chunk.characters for chunk in chunks), replaced=replaced,
        )

    def ingest_file(
        self,
        path: str | Path,
        *,
        collection: str | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Ingested:
        """Extract text from a file and ingest it."""
        # Imported here: the file tools pull in optional parsers, and importing
        # them at module load would make the whole RAG package depend on them.
        from src.tools.file_analysis import extract_file_text

        target = Path(path)
        if not target.exists():
            raise FileNotFoundError(f"no such file: {target}")

        extracted = extract_file_text(target)
        text = extracted.get("text") or ""
        name = source or target.name

        if not text.strip():
            return Ingested(
                source=name, collection=self.collection_for(collection), chunks=0,
                characters=0, extractor=extracted.get("extractor", "none"),
                note=extracted.get("note") or "no text could be extracted from this file",
            )

        result = self.ingest_text(
            text, source=name, collection=collection,
            metadata={**(metadata or {}), "path": str(target), "bytes": target.stat().st_size},
        )
        result.extractor = extracted.get("extractor", "")
        if extracted.get("note"):
            result.note = extracted["note"]
        return result

    # -- reading ------------------------------------------------------------ #

    def query(
        self,
        query: str,
        *,
        collection: str | None = None,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> list[dict[str, Any]]:
        """The chunks most likely to answer ``query``."""
        if not (query or "").strip():
            return []
        name = self.collection_for(collection)
        hits = self.store.search(name, self.embedder.embed_query(query), top_k=top_k, where=where)
        return [
            {
                "text": hit.text,
                "score": round(hit.score, 4),
                "source": hit.source,
                "chunk": hit.metadata.get("chunk"),
                "metadata": hit.metadata,
            }
            for hit in hits
            if hit.score >= min_score
        ]

    def documents(self, collection: str | None = None) -> list[dict[str, Any]]:
        return self.store.sources(self.collection_for(collection))

    def stats(self, collection: str | None = None) -> dict[str, Any]:
        stats = self.store.stats(self.collection_for(collection))
        stats["embeddings"] = self.embedder.name
        return stats

    def collections(self) -> list[str]:
        return self.store.collections()

    def delete_document(self, source: str, collection: str | None = None) -> int:
        removed = self.store.delete(self.collection_for(collection), where={"source": source})
        logger.info("rag_document_deleted", source=source, chunks=removed)
        return removed

    def drop(self, collection: str) -> bool:
        return self.store.drop(self.collection_for(collection))

    @staticmethod
    def _chunk_id(source: str, index: int) -> str:
        """Stable id, so re-ingesting the same file replaces rather than duplicates."""
        digest = hashlib.blake2b(source.encode("utf-8"), digest_size=8).hexdigest()
        return f"{digest}-{index:05d}"


# --------------------------------------------------------------------------- #

_service: RagService | None = None
_service_lock = threading.Lock()


def get_rag_service() -> RagService:
    """The process-wide service, rebuilt if the configuration changed.

    Configuration is re-read rather than frozen at import, so changing
    RAG_BACKEND in a test or at runtime takes effect instead of being silently
    ignored until restart.
    """
    global _service
    config = RagConfig()
    with _service_lock:
        if _service is None or _service.config.fingerprint() != config.fingerprint():
            _service = RagService(config)
        return _service


def reset_rag_service() -> None:
    """Drop the cached service. For tests and for configuration changes."""
    global _service
    with _service_lock:
        _service = None
