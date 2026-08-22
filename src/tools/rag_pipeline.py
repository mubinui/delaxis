"""Retrieval tools for agents.

These used to be an HTTP client for a separate "RAG Pipeline" service on
``localhost:8003``. Nothing in this repository started that service, so on any
fresh install every one of these tools timed out — retrieval was configured,
documented, offered to agents in the library, and non-functional.

They now run the pipeline in ``src.rag`` directly: chunk, embed, store, search,
in this process. The default store is SQLite in the data directory and the
default embedder needs no API key, so retrieval works immediately after
uploading a file. Pointing ``RAG_BACKEND`` at Qdrant, pgvector, Pinecone, FAISS
or Chroma changes where the vectors live and nothing else.

The function names, arguments and return shapes are unchanged, because the
CrewAI runtime, ``configs/tools.json`` and the workflow knowledge nodes all call
them by that contract.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

import structlog

from src.rag.service import get_rag_service

logger = structlog.get_logger(__name__)


def _enabled() -> bool:
    """Whether retrieval is switched on.

    Kept because deployments set it, though it no longer means "is the remote
    service reachable" — there is no remote service.
    """
    try:
        from src.config.settings import get_settings

        return bool(get_settings().external_services.rag_pipeline_enabled)
    except Exception:  # settings problems must not take retrieval down
        return True


def _disabled(**extra: Any) -> dict[str, Any]:
    return {
        "success": False,
        "error": "Retrieval is disabled (RAG_PIPELINE_ENABLED is false)",
        "message": "Retrieval is disabled",
        **extra,
    }


async def ingest_file(
    collection: Optional[str] = None,
    file_path: str = "",
) -> dict[str, Any]:
    """Index a file so agents can retrieve from it.

    Args:
        collection: Collection to ingest into (defaults to the configured one)
        file_path: Path to the file — PDF, DOCX, XLSX, CSV, JSON or text

    Returns:
        success, message, documents_processed, and error when it failed.
    """
    if not _enabled():
        return _disabled(documents_processed=0)
    if not file_path:
        return {"success": False, "message": "file_path is required",
                "documents_processed": 0, "error": "file_path is required"}

    service = get_rag_service()
    try:
        # Extraction and embedding are blocking, and this runs inside the
        # request loop.
        result = await asyncio.to_thread(
            service.ingest_file, Path(file_path), collection=collection
        )
    except FileNotFoundError as exc:
        return {"success": False, "message": str(exc), "documents_processed": 0,
                "error": str(exc)}
    except Exception as exc:
        logger.exception("rag_ingest_failed", file_path=file_path)
        return {"success": False, "message": f"Ingestion failed: {exc}",
                "documents_processed": 0, "error": str(exc)}

    if not result.chunks:
        return {"success": False, "message": result.note or "nothing to index",
                "documents_processed": 0, "collection": result.collection,
                "error": result.note or "no text could be extracted"}

    return {
        "success": True,
        "message": (
            f"Indexed '{result.source}' as {result.chunks} chunk(s) "
            f"in collection '{result.collection}'"
        ),
        "documents_processed": result.chunks,
        "collection": result.collection,
        "source": result.source,
        "characters": result.characters,
        "replaced": result.replaced,
    }


async def ingest_text(
    text: str,
    source: str = "note",
    collection: Optional[str] = None,
) -> dict[str, Any]:
    """Index text directly, without it having to be a file first."""
    if not _enabled():
        return _disabled(documents_processed=0)
    service = get_rag_service()
    try:
        result = await asyncio.to_thread(
            service.ingest_text, text, source=source, collection=collection
        )
    except Exception as exc:
        logger.exception("rag_ingest_text_failed", source=source)
        return {"success": False, "message": f"Ingestion failed: {exc}",
                "documents_processed": 0, "error": str(exc)}
    return {
        "success": bool(result.chunks),
        "message": f"Indexed '{source}' as {result.chunks} chunk(s)",
        "documents_processed": result.chunks,
        "collection": result.collection,
        "source": result.source,
    }


async def ingest_batch(
    collection: Optional[str] = None,
    file_paths: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Index several files. One failure does not abandon the rest."""
    if not _enabled():
        return _disabled(documents_processed=0)

    results = []
    total = 0
    failures = []
    for path in file_paths or []:
        outcome = await ingest_file(collection=collection, file_path=path)
        results.append(outcome)
        total += int(outcome.get("documents_processed", 0))
        if not outcome.get("success"):
            failures.append({"file": path, "error": outcome.get("error")})

    return {
        "success": bool(file_paths) and not failures,
        "message": f"Indexed {total} chunk(s) from {len(results) - len(failures)} file(s)",
        "documents_processed": total,
        "files": results,
        "failures": failures,
        "error": f"{len(failures)} file(s) failed" if failures else None,
    }


async def query_rag(
    query: str = "",
    collection: Optional[str] = None,
    top_k: int = 5,
    rerank: bool = True,
) -> dict[str, Any]:
    """Retrieve the passages most likely to answer a question.

    Args:
        query: What to search for
        collection: Collection to search (defaults to the configured one)
        top_k: How many passages to return
        rerank: Accepted for compatibility; ranking is by similarity either way

    Returns:
        query, results (text, score, source), total_results, success, error.
    """
    if not _enabled():
        return {"query": query, "results": [], "total_results": 0, **_disabled()}
    if not (query or "").strip():
        return {"query": query, "results": [], "total_results": 0,
                "success": False, "error": "query is required"}

    service = get_rag_service()
    try:
        hits = await asyncio.to_thread(
            service.query, query, collection=collection, top_k=max(1, int(top_k or 5))
        )
    except Exception as exc:
        logger.exception("rag_query_failed", collection=collection)
        return {"query": query, "results": [], "total_results": 0,
                "success": False, "error": str(exc)}

    return {
        "query": query,
        "results": hits,
        "total_results": len(hits),
        "collection": service.collection_for(collection),
        "success": True,
        "error": None,
    }


async def list_files(collection: Optional[str] = None) -> dict[str, Any]:
    """List the documents indexed in a collection."""
    if not _enabled():
        return _disabled(files=[], total_files=0)
    service = get_rag_service()
    try:
        documents = await asyncio.to_thread(service.documents, collection)
    except Exception as exc:
        logger.exception("rag_list_failed", collection=collection)
        return {"collection": collection, "files": [], "total_files": 0,
                "success": False, "error": str(exc)}
    return {
        "collection": service.collection_for(collection),
        "files": [item["source"] for item in documents],
        "documents": documents,
        "total_files": len(documents),
        "success": True,
        "error": None,
    }


async def delete_file(filename: str, collection: Optional[str] = None) -> dict[str, Any]:
    """Remove a document and all of its chunks from a collection."""
    if not _enabled():
        return _disabled()
    if not filename:
        return {"success": False, "message": "filename is required",
                "error": "filename is required"}
    service = get_rag_service()
    try:
        removed = await asyncio.to_thread(service.delete_document, filename, collection)
    except Exception as exc:
        logger.exception("rag_delete_failed", filename=filename)
        return {"success": False, "message": f"Delete failed: {exc}", "error": str(exc)}
    return {
        "success": removed > 0,
        "message": (
            f"Removed '{filename}' ({removed} chunk(s))" if removed
            else f"'{filename}' was not in this collection"
        ),
        "chunks_removed": removed,
        "collection": service.collection_for(collection),
        "error": None if removed else "not found",
    }


async def get_stats(collection: Optional[str] = None) -> dict[str, Any]:
    """Counts and configuration for a collection."""
    if not _enabled():
        return _disabled()
    service = get_rag_service()
    try:
        stats = await asyncio.to_thread(service.stats, collection)
        collections = await asyncio.to_thread(service.collections)
    except Exception as exc:
        logger.exception("rag_stats_failed", collection=collection)
        return {"success": False, "error": str(exc)}
    return {**stats, "collections": collections, "success": True, "error": None}


async def list_collections() -> dict[str, Any]:
    """Every collection this store knows about."""
    if not _enabled():
        return _disabled(collections=[])
    service = get_rag_service()
    try:
        collections = await asyncio.to_thread(service.collections)
    except Exception as exc:
        return {"success": False, "collections": [], "error": str(exc)}
    return {"success": True, "collections": collections,
            "backend": service.store.name, "embeddings": service.embedder.name, "error": None}
