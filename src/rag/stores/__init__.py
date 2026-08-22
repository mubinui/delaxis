"""Choosing a vector store.

Every backend is behind one protocol, so which one is running is a
configuration decision rather than a code decision. ``RAG_BACKEND`` picks it and
everything above this line — chunking, ingestion, the agent tools, the HTTP API
— is unchanged either way.

The default is SQLite, on purpose. The previous implementation required a
separate service that nothing in the repository started, so retrieval was broken
on every fresh install; the default now has to be something that works with
nothing configured, and the rest are upgrades.

Adding another backend is one module implementing the protocol plus one
``register_backend`` call, which is what makes "and others" a small change
rather than a fork.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable

import structlog

from src.rag.stores.base import (
    Record,
    SearchHit,
    VectorStore,
    VectorStoreError,
    cosine,
    matches,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "Record", "SearchHit", "VectorStore", "VectorStoreError", "cosine", "matches",
    "create_store", "register_backend", "available_backends", "normalise_collection",
]


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


# --------------------------------------------------------------------------- #
# Collection names
# --------------------------------------------------------------------------- #

#: The intersection of what every backend accepts. Chroma is the strictest —
#: 3 to 512 characters of [a-zA-Z0-9._-], starting and ending alphanumeric — so
#: a name that satisfies it satisfies the rest. Normalising centrally means
#: switching backends cannot suddenly reject collections that already exist.
_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def normalise_collection(name: str) -> str:
    """A collection name every backend will accept.

    Deliberately lossy and deterministic: two names differing only by characters
    no backend allows should land on the same collection rather than silently
    creating two.
    """
    cleaned = _SAFE.sub("-", (name or "").strip()).strip("-._")
    if not cleaned:
        cleaned = "default"
    if len(cleaned) < 3:
        cleaned = f"{cleaned}-collection"
    if not cleaned[0].isalnum():
        cleaned = f"c{cleaned}"
    if not cleaned[-1].isalnum():
        cleaned = f"{cleaned}0"
    return cleaned[:512]


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #

BackendFactory = Callable[..., VectorStore]
_BACKENDS: dict[str, BackendFactory] = {}


def register_backend(name: str, factory: BackendFactory) -> None:
    """Make another store selectable by ``RAG_BACKEND``."""
    _BACKENDS[name.strip().lower()] = factory


def available_backends() -> list[str]:
    return sorted(_BACKENDS)


# Imports are deferred into the factories: importing this module must not
# require chromadb, faiss, qdrant-client and pinecone all to be installed.

def _sqlite(**options: Any) -> VectorStore:
    from src.rag.stores.sqlite_store import SqliteVectorStore
    return SqliteVectorStore(path=options.get("path") or _env("RAG_SQLITE_PATH") or None)


def _chroma(**options: Any) -> VectorStore:
    from src.rag.stores.chroma_store import ChromaVectorStore
    return ChromaVectorStore(
        persist_directory=options.get("path") or _env("CHROMA_PATH", "./data/chromadb"),
        host=options.get("host") or _env("CHROMA_HOST") or None,
        port=int(options.get("port") or _env("CHROMA_PORT", "0")) or None,
    )


def _faiss(**options: Any) -> VectorStore:
    from src.rag.stores.faiss_store import FaissVectorStore
    return FaissVectorStore(path=options.get("path") or _env("FAISS_PATH", "./data/faiss"))


def _qdrant(**options: Any) -> VectorStore:
    from src.rag.stores.qdrant_store import QdrantVectorStore
    return QdrantVectorStore(
        url=options.get("url") or _env("QDRANT_URL") or None,
        api_key=options.get("api_key") or _env("QDRANT_API_KEY") or None,
        path=options.get("path") or _env("QDRANT_PATH") or None,
        prefer_grpc=str(options.get("prefer_grpc") or _env("QDRANT_PREFER_GRPC")).lower()
        in ("1", "true", "yes"),
    )


def _pgvector(**options: Any) -> VectorStore:
    from src.rag.stores.pgvector_store import PgVectorStore
    dsn = options.get("connection_string") or _env("PGVECTOR_URL") or _env("DATABASE_URL")
    if not dsn:
        raise VectorStoreError(
            "the pgvector backend needs PGVECTOR_URL, e.g. "
            "postgresql://user:pass@localhost:5432/delaxis"
        )
    return PgVectorStore(
        connection_string=dsn,
        table_name=options.get("table_name") or _env("PGVECTOR_TABLE", "rag_embeddings"),
        vector_dimensions=int(options.get("dimensions") or _env("RAG_EMBEDDING_DIMENSIONS", "768")),
    )


def _pinecone(**options: Any) -> VectorStore:
    from src.rag.stores.pinecone_store import PineconeVectorStore
    key = options.get("api_key") or _env("PINECONE_API_KEY")
    if not key:
        raise VectorStoreError("the pinecone backend needs PINECONE_API_KEY")
    return PineconeVectorStore(
        api_key=key,
        index_name=options.get("index_name") or _env("PINECONE_INDEX", "delaxis"),
        dimensions=int(options.get("dimensions") or _env("RAG_EMBEDDING_DIMENSIONS", "1536")),
        cloud=options.get("cloud") or _env("PINECONE_CLOUD", "aws"),
        region=options.get("region") or _env("PINECONE_REGION", "us-east-1"),
    )


for _name, _factory in (
    ("sqlite", _sqlite),
    ("chromadb", _chroma),
    ("faiss", _faiss),
    ("qdrant", _qdrant),
    ("pgvector", _pgvector),
    ("pinecone", _pinecone),
):
    register_backend(_name, _factory)

#: Names people actually type, mapped to the backend they meant.
ALIASES = {
    "": "sqlite",
    "local": "sqlite",
    "default": "sqlite",
    "memory": "sqlite",
    "chroma": "chromadb",
    "postgres": "pgvector",
    "postgresql": "pgvector",
    "pg": "pgvector",
    "faiss-cpu": "faiss",
}


def create_store(backend: str | None = None, **options: Any) -> VectorStore:
    """Build the configured store.

    A backend that is named but unusable is an error rather than a silent
    fallback: someone who set ``RAG_BACKEND=pinecone`` needs to hear that the
    key is missing, not have their documents quietly land in a local file they
    will never think to look in.
    """
    chosen = (backend or _env("RAG_BACKEND") or "sqlite").strip().lower()
    chosen = ALIASES.get(chosen, chosen)

    factory = _BACKENDS.get(chosen)
    if factory is None:
        raise VectorStoreError(
            f"unknown vector store backend {chosen!r}. "
            f"Available: {', '.join(available_backends())}"
        )
    store = factory(**options)
    logger.info("rag_store_ready", backend=store.name)
    return store
