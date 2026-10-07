"""RAG service configuration management endpoints.

This module provides REST API endpoints for managing the RAG Pipeline service
configuration used by workflows for document retrieval and semantic search.

The remote RAG Pipeline service (RAG_PIPELINE_BASE_URL) handles all vector
database operations internally. No local vector DB setup is required.

See the RAG service Swagger docs at <RAG_PIPELINE_BASE_URL>/docs
"""

import json
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from src.api.auth import CurrentUser, get_current_user
from src.audit_logging import get_logger
from src.config.config_loader import get_config_loader

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/rag-service", tags=["rag-service"])


def _get_vector_dbs_config_path() -> Path:
    """Get the path to the vector databases configuration file."""
    return Path("configs") / "vector_databases.json"


def _load_vector_dbs_config() -> dict:
    """Load vector databases configuration from file using config loader."""
    try:
        loader = get_config_loader()
        # The config loader loads the file content.
        # The file structure is { "qdrant": { ... }, "chroma": { ... } }
        # But get_config returns the whole dict.
        return loader.get_config("vector_databases")
    except FileNotFoundError:
        return {}


def _save_vector_dbs_config(config: dict) -> None:
    """Save vector databases configuration to file."""
    config_path = _get_vector_dbs_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    # Trigger reload in config loader
    try:
        loader = get_config_loader()
        loader._reload_single_file(config_path)
    except Exception as e:
        logger.warning(f"Failed to reload config in loader: {e}")


class VectorDbConfigResponse(BaseModel):
    id: str
    type: str
    enabled: bool
    base_url: str
    default_collection: str
    timeout: int
    description: str
    health_status: str | None = None
    health_details: dict[str, Any] | None = None


@router.get("", response_model=VectorDbConfigResponse)
async def get_rag_service_config(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> VectorDbConfigResponse:
    """
    Get RAG service configuration and health status.

    Returns the remote RAG Pipeline service configuration including:
    - Base URL and connectivity settings
    - Default collection name
    - Current health status
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Getting RAG service config",
        request_id=request_id,
    )

    try:
        config = _load_vector_dbs_config()

        # Get rag_service config or fall back to env vars
        rag_config = config.get("rag_service", {})

        base_url = rag_config.get("base_url") or os.getenv(
            "RAG_PIPELINE_BASE_URL", "http://localhost:8003"
        )
        enabled = rag_config.get(
            "enabled", os.getenv("RAG_PIPELINE_ENABLED", "true").lower() == "true"
        )
        default_collection = rag_config.get("default_collection") or os.getenv(
            "RAG_PIPELINE_DEFAULT_COLLECTION", "knowledge_base"
        )
        timeout = rag_config.get("timeout", int(os.getenv("RAG_PIPELINE_TIMEOUT", "60")))
        description = rag_config.get("description", "Remote RAG Pipeline service")

        # Check health
        health_status = "unknown"
        health_details = None

        if enabled and base_url:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"{base_url}/health")
                    if response.status_code == 200:
                        health_data = response.json()
                        health_status = health_data.get("status", "healthy")
                        health_details = health_data
                    else:
                        health_status = "unhealthy"
            except Exception as e:
                logger.warning(f"Failed to check RAG service health: {e}")
                health_status = "unreachable"

        return VectorDbConfigResponse(
            id="rag_service",
            type="rag_pipeline",
            enabled=enabled,
            base_url=base_url,
            default_collection=default_collection,
            timeout=timeout,
            description=description,
            health_status=health_status,
            health_details=health_details,
        )

    except Exception as e:
        logger.error(
            "Failed to get RAG service config",
            request_id=request_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get RAG service config: {str(e)}",
        ) from e


@router.get("/collections", response_model=dict[str, Any])
async def list_rag_collections(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    List available collections in the RAG service.

    Returns list of collections available for querying and ingestion.
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Listing RAG collections",
        request_id=request_id,
    )

    try:
        config = _load_vector_dbs_config()
        rag_config = config.get("rag_service", {})

        base_url = rag_config.get("base_url") or os.getenv(
            "RAG_PIPELINE_BASE_URL", "http://localhost:8003"
        )

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/collections")
            response.raise_for_status()
            return response.json()

    except httpx.HTTPError as e:
        logger.error(
            "Failed to list RAG collections",
            request_id=request_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"RAG service unavailable: {str(e)}",
        ) from e
    except Exception as e:
        logger.error(
            "Failed to list RAG collections",
            request_id=request_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list RAG collections: {str(e)}",
        ) from e
