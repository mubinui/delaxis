"""Prompt template management endpoints."""

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from src.api.auth import CurrentUser, get_current_user, require_admin
from src.api.models import (
    ConfigHistoryEntry,
    ConfigHistoryResponse,
    PromptTemplateCreateRequest,
    PromptTemplateResponse,
    PromptTemplateUpdateRequest,
)
from src.audit_logging import get_logger
from src.config.paths import config_path
from src.config.prompt_models import extract_variables
from src.config.versioned_service import ConfigVersion, VersionedConfigService

VERSIONED_SERVICE_AVAILABLE = True

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


def _get_prompts_config_path() -> Path:
    """Get the path to the prompts configuration file."""
    return config_path("prompt_templates.json")


def _load_prompts_config() -> dict[str, Any]:
    """Load prompts configuration from file."""
    config_path = _get_prompts_config_path()

    if not config_path.exists():
        return {"version": "1.0", "contexts": [], "fallbacks": {}}

    with open(config_path) as f:
        data: dict[str, Any] = json.load(f)
    return data


def _save_prompts_config(config: dict[str, Any]) -> None:
    """Save prompts configuration to file."""
    config_path = _get_prompts_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


def _get_versioned_service() -> VersionedConfigService | None:
    """Get versioned config service if database is configured."""
    if not VERSIONED_SERVICE_AVAILABLE:
        return None
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        service = VersionedConfigService(database_url=database_url)
        if service.is_available():
            return service
    return None


def _prompt_to_response(
    prompt: dict[str, Any], version_info: ConfigVersion | None = None
) -> PromptTemplateResponse:
    """Convert prompt dict to response model."""
    response_data = {
        "id": prompt["id"],
        "name": prompt.get("name", prompt["id"]),
        "description": prompt.get("description", ""),
        "template": prompt.get("prompt", ""),
        "variables": prompt.get("variables", []),
        "category": prompt.get("category"),
    }

    if version_info:
        response_data["version"] = version_info.version
        response_data["etag"] = version_info.etag
        response_data["last_updated"] = version_info.last_updated.isoformat()

    return PromptTemplateResponse(**response_data)


@router.get("", response_model=list[PromptTemplateResponse])
async def list_prompts(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> list[PromptTemplateResponse]:
    """
    List all prompt templates.

    Args:
        request: FastAPI request object
        current_user: Current authenticated user

    Returns:
        List of prompt template configurations

    Requirements: 2.1, 2.2, 7.1
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Listing prompts",
        request_id=request_id,
    )

    try:
        config = _load_prompts_config()
        versioned_service = _get_versioned_service()

        responses = []
        for prompt in config.get("contexts", []):
            if versioned_service:
                _, version_info = versioned_service.get_config(
                    "prompt", prompt["id"], current_user.user_id
                )
                responses.append(_prompt_to_response(prompt, version_info))
            else:
                responses.append(_prompt_to_response(prompt))

        return responses

    except Exception as e:
        logger.error(
            "Failed to list prompts",
            request_id=request_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list prompts: {str(e)}",
        ) from e


@router.post("", response_model=PromptTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt(
    request: Request,
    body: PromptTemplateCreateRequest,
    current_user: CurrentUser = Depends(require_admin),
) -> PromptTemplateResponse:
    """
    Create a new prompt template.

    Args:
        request: FastAPI request object
        body: Prompt template creation request
        current_user: Current authenticated user (admin required)

    Returns:
        Created prompt template

    Requirements: 2.1, 2.2, 2.3, 7.1
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Creating prompt",
        request_id=request_id,
        prompt_id=body.id,
    )

    try:
        # Load existing config
        config = _load_prompts_config()

        # Check if prompt already exists
        if any(p["id"] == body.id for p in config.get("contexts", [])):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Prompt already exists: {body.id}",
            )

        # Extract variables from template if not provided
        variables = body.variables if body.variables else extract_variables(body.template)

        # Create prompt dict
        prompt_dict = {
            "id": body.id,
            "name": body.name,
            "description": body.description,
            "prompt": body.template,
            "variables": variables,
        }

        if body.category:
            prompt_dict["category"] = body.category

        # Add to config
        if "contexts" not in config:
            config["contexts"] = []
        config["contexts"].append(prompt_dict)

        # Save config
        _save_prompts_config(config)

        # Create version snapshot if versioning is enabled
        versioned_service = _get_versioned_service()
        version_info = None
        if versioned_service:
            success, etag, _ = versioned_service.update_config(
                config_type="prompt",
                config_id=body.id,
                updates=prompt_dict,
                user_id=current_user.user_id,
                change_summary="Initial prompt creation",
            )
            if success:
                _, version_info = versioned_service.get_config(
                    "prompt", body.id, current_user.user_id
                )

        logger.info(
            "Created prompt",
            request_id=request_id,
            prompt_id=body.id,
        )

        return _prompt_to_response(prompt_dict, version_info)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to create prompt",
            request_id=request_id,
            prompt_id=body.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create prompt: {str(e)}",
        ) from e


@router.get("/{prompt_id}", response_model=PromptTemplateResponse)
async def get_prompt(
    request: Request,
    prompt_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> PromptTemplateResponse:
    """
    Get prompt template by ID.

    Args:
        request: FastAPI request object
        prompt_id: Prompt identifier
        current_user: Current authenticated user

    Returns:
        Prompt template configuration

    Requirements: 2.1, 2.2, 2.3, 7.1
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Getting prompt",
        request_id=request_id,
        prompt_id=prompt_id,
    )

    try:
        config = _load_prompts_config()

        # Find prompt
        prompt = next((p for p in config.get("contexts", []) if p["id"] == prompt_id), None)

        if prompt is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Prompt not found: {prompt_id}",
            )

        # Get version info if available
        versioned_service = _get_versioned_service()
        version_info = None
        if versioned_service:
            _, version_info = versioned_service.get_config(
                "prompt", prompt_id, current_user.user_id
            )

        return _prompt_to_response(prompt, version_info)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get prompt",
            request_id=request_id,
            prompt_id=prompt_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get prompt: {str(e)}",
        ) from e


@router.put("/{prompt_id}", response_model=PromptTemplateResponse)
async def update_prompt(
    request: Request,
    prompt_id: str,
    body: PromptTemplateUpdateRequest,
    current_user: CurrentUser = Depends(require_admin),
    if_match: str | None = Header(None),
) -> PromptTemplateResponse:
    """
    Update prompt template with optimistic locking.

    Args:
        request: FastAPI request object
        prompt_id: Prompt identifier
        body: Prompt template update request
        current_user: Current authenticated user (admin required)
        if_match: Optional version token (ETag) for optimistic locking

    Returns:
        Updated prompt template

    Requirements: 2.2, 2.3, 2.4, 7.1, 7.2
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Updating prompt",
        request_id=request_id,
        prompt_id=prompt_id,
    )

    try:
        config = _load_prompts_config()

        # Find prompt
        prompt_idx = next(
            (i for i, p in enumerate(config.get("contexts", [])) if p["id"] == prompt_id), None
        )

        if prompt_idx is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Prompt not found: {prompt_id}",
            )

        # Update prompt
        prompt = config["contexts"][prompt_idx]
        update_data = body.model_dump(exclude_unset=True)

        # Handle template field mapping
        if "template" in update_data:
            prompt["prompt"] = update_data.pop("template")
            # Auto-extract variables if template changed
            if "variables" not in update_data:
                prompt["variables"] = extract_variables(prompt["prompt"])

        # Apply other updates
        for key, value in update_data.items():
            if value is not None:
                prompt[key] = value

        # Check for version conflict if versioning is enabled
        versioned_service = _get_versioned_service()
        version_info = None

        if versioned_service and if_match:
            success, result, conflict = versioned_service.update_config(
                config_type="prompt",
                config_id=prompt_id,
                updates=prompt,
                version_token=if_match,
                user_id=current_user.user_id,
                change_summary="Prompt update",
            )

            if not success and conflict:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=conflict,
                )

            if success:
                _, version_info = versioned_service.get_config(
                    "prompt", prompt_id, current_user.user_id
                )
        elif versioned_service:
            # No version token provided, just update
            versioned_service.update_config(
                config_type="prompt",
                config_id=prompt_id,
                updates=prompt,
                user_id=current_user.user_id,
                change_summary="Prompt update",
            )
            _, version_info = versioned_service.get_config(
                "prompt", prompt_id, current_user.user_id
            )

        # Save config
        _save_prompts_config(config)

        logger.info(
            "Updated prompt",
            request_id=request_id,
            prompt_id=prompt_id,
        )

        return _prompt_to_response(prompt, version_info)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to update prompt",
            request_id=request_id,
            prompt_id=prompt_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update prompt: {str(e)}",
        ) from e


@router.delete("/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt(
    request: Request,
    prompt_id: str,
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    """
    Delete prompt template.

    Args:
        request: FastAPI request object
        prompt_id: Prompt identifier
        current_user: Current authenticated user (admin required)

    Requirements: 2.2, 7.1
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Deleting prompt",
        request_id=request_id,
        prompt_id=prompt_id,
    )

    try:
        config = _load_prompts_config()

        # Find and remove prompt
        original_count = len(config.get("contexts", []))
        config["contexts"] = [p for p in config.get("contexts", []) if p["id"] != prompt_id]

        if len(config["contexts"]) == original_count:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Prompt not found: {prompt_id}",
            )

        # Save config
        _save_prompts_config(config)

        logger.info(
            "Deleted prompt",
            request_id=request_id,
            prompt_id=prompt_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to delete prompt",
            request_id=request_id,
            prompt_id=prompt_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete prompt: {str(e)}",
        ) from e


@router.get("/{prompt_id}/history", response_model=ConfigHistoryResponse)
async def get_prompt_history(
    request: Request,
    prompt_id: str,
    limit: int = 10,
    current_user: CurrentUser = Depends(get_current_user),
) -> ConfigHistoryResponse:
    """
    Get prompt template version history.

    Args:
        request: FastAPI request object
        prompt_id: Prompt identifier
        limit: Maximum number of history entries to return
        current_user: Current authenticated user

    Returns:
        Configuration history with versions

    Requirements: 9.2
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Getting prompt history",
        request_id=request_id,
        prompt_id=prompt_id,
    )

    try:
        versioned_service = _get_versioned_service()

        if not versioned_service:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Version history not available (database not configured)",
            )

        history = versioned_service.get_config_history(
            config_type="prompt",
            config_id=prompt_id,
            limit=limit,
            user_id=current_user.user_id,
        )

        if not history:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No history found for prompt: {prompt_id}",
            )

        history_entries = [ConfigHistoryEntry(**entry) for entry in history]

        return ConfigHistoryResponse(
            config_type="prompt",
            config_id=prompt_id,
            history=history_entries,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get prompt history",
            request_id=request_id,
            prompt_id=prompt_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get prompt history: {str(e)}",
        ) from e
