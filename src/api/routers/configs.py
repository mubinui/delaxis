"""Configuration versioning API endpoints with optimistic locking."""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.api.auth import CurrentUser, require_admin, require_user
from src.audit_logging import AuditLogger
from src.config.config_loader import get_config_loader
from src.config.settings import get_settings

# Versioned config service is optional and requires PostgreSQL
try:
    from src.config.versioned_service import VersionedConfigService

    VERSIONED_SERVICE_AVAILABLE = True
except ImportError:
    VersionedConfigService = None
    VERSIONED_SERVICE_AVAILABLE = False

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/configs", tags=["configs"])


# Request/Response Models
class ConfigResponse(BaseModel):
    """Configuration response with version metadata."""

    config_type: str
    config_id: str
    config_data: dict
    version: int
    etag: str
    last_updated: str
    updated_by: str | None = None


class ConfigUpdateRequest(BaseModel):
    """Configuration update request."""

    config_data: dict = Field(..., description="Updated configuration data")
    change_summary: str | None = Field(None, description="Summary of changes made")


class ConfigHistoryEntry(BaseModel):
    """Configuration history entry."""

    version: int
    etag: str
    created_at: str
    updated_by: str | None
    change_summary: str | None
    config_data: dict


class ConfigHistoryResponse(BaseModel):
    """Configuration history response."""

    config_type: str
    config_id: str
    history: list[ConfigHistoryEntry]


class RollbackRequest(BaseModel):
    """Configuration rollback request."""

    target_version: int = Field(..., description="Version to rollback to")


class ConflictResponse(BaseModel):
    """Response when a configuration conflict is detected."""

    status: str = "conflict"
    current_version: int
    current_etag: str
    current_config: dict
    provided_version: int | None = None
    provided_etag: str | None = None
    diff: dict


# Dependency to get versioned config service
def get_versioned_config_service() -> "VersionedConfigService":
    """Get VersionedConfigService instance."""
    if not VERSIONED_SERVICE_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration versioning requires PostgreSQL which is not available",
        )
    settings = get_settings()
    audit_logger = AuditLogger()
    service = VersionedConfigService(
        database_url=settings.database_url,
        audit_logger=audit_logger,
    )
    if not service.is_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration versioning backend is not initialized. Apply database migrations to enable version history.",
        )
    return service


@router.get("/{config_type}/{config_id}", response_model=ConfigResponse)
async def get_config(
    request: Request,
    config_type: str,
    config_id: str,
    current_user: CurrentUser = Depends(require_user),
    service: VersionedConfigService = Depends(get_versioned_config_service),
) -> ConfigResponse:
    """
    Get configuration with version metadata.

    Args:
        request: FastAPI request object
        config_type: Type of config ('agent', 'workflow', 'tool', 'vector_db')
        config_id: Configuration identifier
        current_user: Current authenticated user
        service: VersionedConfigService instance

    Returns:
        Configuration with version metadata

    Requirements: 19.1, 19.5
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Getting config",
        request_id=request_id,
        config_type=config_type,
        config_id=config_id,
        user_id=current_user.user_id,
    )

    try:
        config_data, version_info = service.get_config(
            config_type=config_type,
            config_id=config_id,
            user_id=current_user.user_id,
        )

        if config_data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Configuration not found: {config_type}/{config_id}",
            )

        return ConfigResponse(
            config_type=config_type,
            config_id=config_id,
            config_data=config_data,
            version=version_info.version,
            etag=version_info.etag,
            last_updated=version_info.last_updated.isoformat(),
            updated_by=version_info.updated_by,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get config",
            request_id=request_id,
            config_type=config_type,
            config_id=config_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get configuration: {str(e)}",
        ) from e


@router.put("/{config_type}/{config_id}", response_model=ConfigResponse)
async def update_config(
    request: Request,
    config_type: str,
    config_id: str,
    body: ConfigUpdateRequest,
    if_match: str | None = Header(None, description="Version token (etag or version number)"),
    current_user: CurrentUser = Depends(require_admin),
    service: VersionedConfigService = Depends(get_versioned_config_service),
) -> ConfigResponse:
    """
    Update configuration with optimistic locking.

    Requires If-Match header with version token (etag or version number).
    Returns HTTP 409 Conflict if version token doesn't match current version.

    Args:
        request: FastAPI request object
        config_type: Type of config ('agent', 'workflow', 'tool', 'vector_db')
        config_id: Configuration identifier
        body: Configuration update request
        if_match: Version token from If-Match header
        current_user: Current authenticated user
        service: VersionedConfigService instance

    Returns:
        Updated configuration with new version metadata

    Requirements: 19.1, 19.2, 19.3, 19.5
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Updating config",
        request_id=request_id,
        config_type=config_type,
        config_id=config_id,
        user_id=current_user.user_id,
        version_token=if_match,
    )

    try:
        success, result, conflict = service.update_config(
            config_type=config_type,
            config_id=config_id,
            updates=body.config_data,
            version_token=if_match,
            user_id=current_user.user_id,
            change_summary=body.change_summary,
        )

        if not success:
            if conflict:
                # Version conflict detected
                logger.warning(
                    "Config update conflict",
                    request_id=request_id,
                    config_type=config_type,
                    config_id=config_id,
                    user_id=current_user.user_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=conflict,
                )
            else:
                # Not found
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Configuration not found: {config_type}/{config_id}",
                )

        # Get updated config
        config_data, version_info = service.get_config(
            config_type=config_type,
            config_id=config_id,
            user_id=current_user.user_id,
        )

        logger.info(
            "Updated config",
            request_id=request_id,
            config_type=config_type,
            config_id=config_id,
            user_id=current_user.user_id,
            new_version=version_info.version,
        )

        return ConfigResponse(
            config_type=config_type,
            config_id=config_id,
            config_data=config_data,
            version=version_info.version,
            etag=version_info.etag,
            last_updated=version_info.last_updated.isoformat(),
            updated_by=version_info.updated_by,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to update config",
            request_id=request_id,
            config_type=config_type,
            config_id=config_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update configuration: {str(e)}",
        ) from e


@router.get("/{config_type}/{config_id}/history", response_model=ConfigHistoryResponse)
async def get_config_history(
    request: Request,
    config_type: str,
    config_id: str,
    limit: int = 10,
    current_user: CurrentUser = Depends(require_user),
    service: VersionedConfigService = Depends(get_versioned_config_service),
) -> ConfigHistoryResponse:
    """
    Get configuration change history.

    Args:
        request: FastAPI request object
        config_type: Type of config ('agent', 'workflow', 'tool', 'vector_db')
        config_id: Configuration identifier
        limit: Maximum number of history entries to return
        current_user: Current authenticated user
        service: VersionedConfigService instance

    Returns:
        Configuration change history

    Requirements: 19.4, 19.5
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Getting config history",
        request_id=request_id,
        config_type=config_type,
        config_id=config_id,
        user_id=current_user.user_id,
        limit=limit,
    )

    try:
        history = service.get_config_history(
            config_type=config_type,
            config_id=config_id,
            limit=limit,
            user_id=current_user.user_id,
        )

        return ConfigHistoryResponse(
            config_type=config_type,
            config_id=config_id,
            history=[ConfigHistoryEntry(**entry) for entry in history],
        )

    except Exception as e:
        logger.error(
            "Failed to get config history",
            request_id=request_id,
            config_type=config_type,
            config_id=config_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get configuration history: {str(e)}",
        ) from e


@router.post("/{config_type}/{config_id}/rollback", response_model=ConfigResponse)
async def rollback_config(
    request: Request,
    config_type: str,
    config_id: str,
    body: RollbackRequest,
    current_user: CurrentUser = Depends(require_admin),
    service: VersionedConfigService = Depends(get_versioned_config_service),
) -> ConfigResponse:
    """
    Rollback configuration to a previous version.

    Args:
        request: FastAPI request object
        config_type: Type of config ('agent', 'workflow', 'tool', 'vector_db')
        config_id: Configuration identifier
        body: Rollback request with target version
        current_user: Current authenticated user
        service: VersionedConfigService instance

    Returns:
        Configuration after rollback with new version metadata

    Requirements: 19.4, 19.5
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Rolling back config",
        request_id=request_id,
        config_type=config_type,
        config_id=config_id,
        user_id=current_user.user_id,
        target_version=body.target_version,
    )

    try:
        success, result = service.rollback_config(
            config_type=config_type,
            config_id=config_id,
            target_version=body.target_version,
            user_id=current_user.user_id,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result,
            )

        # Get rolled back config
        config_data, version_info = service.get_config(
            config_type=config_type,
            config_id=config_id,
            user_id=current_user.user_id,
        )

        logger.info(
            "Rolled back config",
            request_id=request_id,
            config_type=config_type,
            config_id=config_id,
            user_id=current_user.user_id,
            target_version=body.target_version,
            new_version=version_info.version,
        )

        return ConfigResponse(
            config_type=config_type,
            config_id=config_id,
            config_data=config_data,
            version=version_info.version,
            etag=version_info.etag,
            last_updated=version_info.last_updated.isoformat(),
            updated_by=version_info.updated_by,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to rollback config",
            request_id=request_id,
            config_type=config_type,
            config_id=config_id,
            target_version=body.target_version,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to rollback configuration: {str(e)}",
        ) from e


@router.post("/reload", status_code=status.HTTP_204_NO_CONTENT)
async def reload_configurations(
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    """
    Manually reload all configuration files.

    Forces a reload of all JSON configuration files from disk.
    Useful after manual file edits or deployment updates.

    Args:
        request: FastAPI request object
        current_user: Current authenticated admin user

    Requirements: Admin access required
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Reloading all configurations",
        request_id=request_id,
        user=current_user.username,
    )

    try:
        loader = get_config_loader()
        loader.reload_all()

        logger.info(
            "Successfully reloaded all configurations",
            request_id=request_id,
        )

    except Exception as e:
        logger.error(
            "Failed to reload configurations",
            request_id=request_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reload configurations: {str(e)}",
        ) from e


@router.get("/status")
async def get_configuration_status(
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
) -> dict[str, Any]:
    """
    Get status of all loaded configurations.

    Returns information about loaded configuration files,
    including versions and last load timestamps.

    Args:
        request: FastAPI request object
        current_user: Current authenticated admin user

    Returns:
        Configuration status information

    Requirements: Admin access required
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Getting configuration status",
        request_id=request_id,
    )

    try:
        loader = get_config_loader()

        status_info = {
            "hot_reload_enabled": loader.enable_hot_reload,
            "config_directory": str(loader.config_dir),
            "configurations": {},
        }

        # Get status for each configuration type
        for config_name in ["agents", "tools", "workflows", "api_providers", "prompt_templates"]:
            if loader.is_loaded(config_name):
                status_info["configurations"][config_name] = {
                    "loaded": True,
                    "version": loader.get_config_version(config_name),
                    "last_loaded": loader.get_last_loaded(config_name).isoformat()
                    if loader.get_last_loaded(config_name)
                    else None,
                }
            else:
                status_info["configurations"][config_name] = {"loaded": False}

        return status_info

    except Exception as e:
        logger.error(
            "Failed to get configuration status",
            request_id=request_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get configuration status: {str(e)}",
        ) from e
