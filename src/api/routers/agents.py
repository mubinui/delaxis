"""Agent configuration management endpoints."""

import copy
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.api.auth import CurrentUser, get_current_user, require_admin
from src.api.models import (
    AgentConfigCreateRequest,
    AgentConfigResponse,
    AgentConfigUpdateRequest,
)
from src.audit_logging import get_logger
from src.config.config_loader import get_config_loader
from src.config.dependency_validation import DependencyError, get_validator
from src.config.paths import config_path

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def _get_agents_config_path() -> Path:
    """Get the path to the agents configuration file."""
    return config_path("agents.json")


PLACEHOLDER_INSTRUCTIONS = {"you are a helpful ai assistant.", "you are a helpful assistant."}


def _require_instructions(system_message: str | None) -> None:
    """An agent is its instructions; refuse to store one without them.

    Generic stand-in text is refused too: it used to be the default, so every
    agent created without thought silently became "a helpful AI assistant".
    """
    text = (system_message or "").strip()
    if not text or text.lower() in PLACEHOLDER_INSTRUCTIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "type": "validation_error",
                "message": "The agent needs instructions: say what it is for and how it should "
                "behave (system_message).",
            },
        )


def _load_agents_config() -> dict[str, Any]:
    """Load agents configuration from file using config loader."""
    try:
        loader = get_config_loader()
        # A copy: handlers edit the result and then save it. Editing the loader's
        # own cache in place meant a rejected or failed save still changed what
        # every later request saw, and any caller that forgot to save leaked.
        return copy.deepcopy(loader.get_config("agents"))
    except FileNotFoundError:
        return {"version": "1.0", "agents": []}


def _save_agents_config(config: dict[str, Any]) -> None:
    """Save agents configuration to file."""
    config_path = _get_agents_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    get_config_loader().set_config("agents", copy.deepcopy(config))

    # Trigger reload in config loader
    try:
        loader = get_config_loader()
        loader._reload_single_file(config_path)
    except Exception as e:
        logger.warning(f"Failed to reload config in loader: {e}")


@router.post("", response_model=AgentConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_agent_config(
    request: Request,
    body: AgentConfigCreateRequest,
    current_user: CurrentUser = Depends(require_admin),
) -> AgentConfigResponse:
    """
    Create a new agent configuration.

    Args:
        request: FastAPI request object
        body: Agent configuration request

    Returns:
        Created agent configuration

    Requirements: 2.1, 2.2, 3.1
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Creating agent config",
        request_id=request_id,
        agent_id=body.id,
    )

    _require_instructions(body.system_message)

    try:
        # Load existing config
        config = _load_agents_config()

        # Check if agent already exists
        if any(a["id"] == body.id for a in config["agents"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Agent already exists: {body.id}",
            )

        # Validate tool references
        validator = get_validator()
        try:
            validator.validate_agent_tool_references(body.id, body.tools)
        except DependencyError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "type": "dependency_error",
                    "message": str(e),
                    "dependencies": {
                        "missing": e.missing,
                        "available": e.available,
                    },
                },
            ) from e

        # Add new agent
        agent_dict = body.model_dump()
        config["agents"].append(agent_dict)

        # Save config
        _save_agents_config(config)

        logger.info(
            "Created agent config",
            request_id=request_id,
            agent_id=body.id,
        )

        return AgentConfigResponse(**agent_dict)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to create agent config",
            request_id=request_id,
            agent_id=body.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create agent config: {str(e)}",
        ) from e


@router.get("", response_model=list[AgentConfigResponse])
async def list_agents(
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> list[AgentConfigResponse]:
    """
    List all agent configurations.

    Args:
        request: FastAPI request object

    Returns:
        List of agent configurations

    Requirements: 2.1, 2.2, 3.1
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Listing agents",
        request_id=request_id,
    )

    try:
        config = _load_agents_config()
        return [AgentConfigResponse(**agent) for agent in config["agents"]]

    except Exception as e:
        logger.error(
            "Failed to list agents",
            request_id=request_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list agents: {str(e)}",
        ) from e


@router.get("/{agent_id}", response_model=AgentConfigResponse)
async def get_agent_config(
    request: Request,
    agent_id: str,
    current_user: CurrentUser = Depends(get_current_user),
) -> AgentConfigResponse:
    """
    Get agent configuration by ID.

    Args:
        request: FastAPI request object
        agent_id: Agent identifier

    Returns:
        Agent configuration

    Requirements: 2.1, 2.2, 3.1
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Getting agent config",
        request_id=request_id,
        agent_id=agent_id,
    )

    try:
        config = _load_agents_config()

        # Find agent
        agent = next((a for a in config["agents"] if a["id"] == agent_id), None)

        if agent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent not found: {agent_id}",
            )

        return AgentConfigResponse(**agent)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get agent config",
            request_id=request_id,
            agent_id=agent_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agent config: {str(e)}",
        ) from e


@router.put("/{agent_id}", response_model=AgentConfigResponse)
async def update_agent_config(
    request: Request,
    agent_id: str,
    body: AgentConfigUpdateRequest,
    current_user: CurrentUser = Depends(require_admin),
) -> AgentConfigResponse:
    """
    Update agent configuration.

    Args:
        request: FastAPI request object
        agent_id: Agent identifier
        body: Agent configuration update request

    Returns:
        Updated agent configuration

    Requirements: 2.1, 2.2, 3.1
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Updating agent config",
        request_id=request_id,
        agent_id=agent_id,
    )

    try:
        config = _load_agents_config()

        # Find agent
        agent_idx = next((i for i, a in enumerate(config["agents"]) if a["id"] == agent_id), None)

        if agent_idx is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent not found: {agent_id}",
            )

        # Update agent
        agent = config["agents"][agent_idx]
        update_data = body.model_dump(exclude_unset=True)
        if "system_message" in update_data:
            _require_instructions(update_data["system_message"])

        # Validate tool references if tools are being updated
        if "tools" in update_data:
            validator = get_validator()
            try:
                validator.validate_agent_tool_references(agent_id, update_data["tools"])
            except DependencyError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={
                        "type": "dependency_error",
                        "message": str(e),
                        "dependencies": {
                            "missing": e.missing,
                            "available": e.available,
                        },
                    },
                ) from e

        agent.update(update_data)

        # Save config
        _save_agents_config(config)

        logger.info(
            "Updated agent config",
            request_id=request_id,
            agent_id=agent_id,
        )

        return AgentConfigResponse(**agent)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to update agent config",
            request_id=request_id,
            agent_id=agent_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update agent config: {str(e)}",
        ) from e


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent_config(
    request: Request,
    agent_id: str,
    current_user: CurrentUser = Depends(require_admin),
) -> None:
    """
    Delete agent configuration.

    Args:
        request: FastAPI request object
        agent_id: Agent identifier

    Requirements: 2.1, 2.2, 3.1
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Deleting agent config",
        request_id=request_id,
        agent_id=agent_id,
    )

    try:
        config = _load_agents_config()

        # Check if agent exists
        if not any(a["id"] == agent_id for a in config["agents"]):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent not found: {agent_id}",
            )

        # Check for dependencies before deletion
        validator = get_validator()
        try:
            validator.validate_agent_deletion(agent_id)
        except DependencyError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "type": "dependency_error",
                    "message": str(e),
                    "dependents": e.dependents,
                },
            ) from e

        # Remove agent
        config["agents"] = [a for a in config["agents"] if a["id"] != agent_id]

        # Save config
        _save_agents_config(config)

        logger.info(
            "Deleted agent config",
            request_id=request_id,
            agent_id=agent_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to delete agent config",
            request_id=request_id,
            agent_id=agent_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete agent config: {str(e)}",
        ) from e
