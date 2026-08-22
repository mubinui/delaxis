"""Retrieval endpoints: collections, ingestion, search.

Upload-and-index is one request rather than two. Uploading a file and then
separately asking for it to be indexed is a state machine with a failure mode
in the middle — a file on disk that nobody indexed and nothing will retrieve —
and every caller would have to implement the same retry.

Which vector store and which embedding model are behind this is configuration,
not part of the contract, so ``/config`` reports what is actually running.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from src.audit_logging import get_logger
from src.rag.embeddings import PROVIDERS
from src.rag.service import get_rag_service
from src.rag.stores import VectorStoreError, available_backends
from src.tools.file_analysis import (
    ALLOWED_SUFFIXES,
    MAX_UPLOAD_BYTES,
    save_uploaded_bytes,
    uploads_dir,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/rag", tags=["rag"])


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=50)
    #: Equality filter on chunk metadata, e.g. {"source": "handbook.pdf"}.
    where: Optional[dict[str, Any]] = None
    min_score: float = Field(default=0.0, ge=-1.0, le=1.0)


class TextRequest(BaseModel):
    text: str = Field(min_length=1)
    source: str = Field(default="note", max_length=300)
    metadata: Optional[dict[str, Any]] = None


def _service():
    return get_rag_service()


@router.get("/config")
async def configuration() -> dict[str, Any]:
    """What retrieval is actually running, and what else it could run."""
    service = _service()
    try:
        backend = service.store.name
        embeddings = service.embedder.name
        healthy = True
        detail = None
    except VectorStoreError as exc:
        # A misconfigured backend should be visible here rather than only
        # surfacing when someone tries to ingest.
        backend, embeddings, healthy, detail = service.config.backend, None, False, str(exc)

    return {
        "backend": backend,
        "embeddings": embeddings,
        "healthy": healthy,
        "detail": detail,
        "default_collection": service.collection_for(None),
        "chunk_chars": service.config.chunk_chars,
        "overlap_chars": service.config.overlap_chars,
        "available_backends": available_backends(),
        "available_embedding_providers": list(PROVIDERS),
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "allowed_extensions": sorted(ALLOWED_SUFFIXES),
    }


@router.get("/collections")
async def list_collections() -> dict[str, Any]:
    service = _service()
    try:
        names = service.collections()
    except VectorStoreError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {
        "collections": [service.stats(name) for name in names],
        "backend": service.store.name,
    }


@router.get("/collections/{collection}")
async def collection_detail(collection: str) -> dict[str, Any]:
    service = _service()
    try:
        return {**service.stats(collection), "documents_detail": service.documents(collection)}
    except VectorStoreError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.post("/collections/{collection}/files", status_code=status.HTTP_201_CREATED)
async def ingest_files(
    collection: str,
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    """Upload files and index them in one call.

    Every file is attempted and reported individually, so one unreadable file in
    a batch does not discard the rest.
    """
    service = _service()
    results: list[dict[str, Any]] = []
    indexed = 0

    for upload in files:
        name = upload.filename or "upload"
        try:
            payload = await upload.read()
            # Raises on a rejected extension or an oversized file, with the
            # reason already written for a person.
            saved = save_uploaded_bytes(name, payload)
            outcome = service.ingest_file(uploads_dir() / saved["name"], collection=collection)
            indexed += outcome.chunks
            results.append({
                "file": saved["name"],
                "indexed": bool(outcome.chunks),
                "chunks": outcome.chunks,
                "characters": outcome.characters,
                "replaced": outcome.replaced,
                "extractor": outcome.extractor,
                "note": outcome.note or None,
                "error": None if outcome.chunks else (outcome.note or "no text extracted"),
            })
        except VectorStoreError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        except ValueError as exc:
            # Rejected by the upload rules: the caller can fix this, so it is
            # reported per file rather than failing the whole batch.
            results.append({"file": name, "indexed": False, "error": str(exc)})
        except Exception as exc:
            logger.exception("rag_upload_failed", extra={"file": name})
            results.append({"file": name, "indexed": False, "error": str(exc)})

    return {
        "collection": service.collection_for(collection),
        "files": results,
        "chunks_indexed": indexed,
        "success": all(item["indexed"] for item in results) if results else False,
    }


@router.post("/collections/{collection}/text", status_code=status.HTTP_201_CREATED)
async def ingest_text(collection: str, request: TextRequest) -> dict[str, Any]:
    service = _service()
    try:
        outcome = service.ingest_text(
            request.text, source=request.source,
            collection=collection, metadata=request.metadata,
        )
    except VectorStoreError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {
        "collection": outcome.collection,
        "source": outcome.source,
        "chunks": outcome.chunks,
        "characters": outcome.characters,
        "replaced": outcome.replaced,
        "success": bool(outcome.chunks),
        "note": outcome.note or None,
    }


@router.post("/collections/{collection}/query")
async def query(collection: str, request: QueryRequest) -> dict[str, Any]:
    service = _service()
    try:
        hits = service.query(
            request.query, collection=collection, top_k=request.top_k,
            where=request.where, min_score=request.min_score,
        )
    except VectorStoreError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {
        "collection": service.collection_for(collection),
        "query": request.query,
        "results": hits,
        "total_results": len(hits),
    }


@router.delete("/collections/{collection}/documents", status_code=status.HTTP_200_OK)
async def delete_document(
    collection: str,
    source: str = Query(..., min_length=1, description="The document's source name"),
) -> dict[str, Any]:
    service = _service()
    try:
        removed = service.delete_document(source, collection)
    except VectorStoreError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    if not removed:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"'{source}' is not indexed in this collection",
        )
    return {"collection": service.collection_for(collection),
            "source": source, "chunks_removed": removed}


@router.delete("/collections/{collection}", status_code=status.HTTP_200_OK)
async def drop_collection(collection: str) -> dict[str, Any]:
    service = _service()
    try:
        dropped = service.drop(collection)
    except VectorStoreError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    if not dropped:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no collection named '{collection}'")
    return {"collection": service.collection_for(collection), "dropped": True}
