"""Tool management endpoints."""

import asyncio
import copy
import inspect
import json
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.api.models import (
    SwaggerImportRequest,
    SwaggerImportResult,
    SwaggerPreviewEndpoint,
    SwaggerPreviewResponse,
    ToolExecutionRequest,
    ToolExecutionResponse,
    ToolRegisterRequest,
    ToolResponse,
    ToolUpdateRequest,
)
from src.audit_logging import get_logger
from src.config.config_loader import get_config_loader
from src.config.dependency_validation import DependencyError, get_validator
from src.config.paths import config_path
from src.config.tool_registry import get_tool_registry
from src.tools.swagger_parser import SwaggerParser, sanitize_tool_id

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


def _get_tools_config_path() -> Path:
    """Get the path to the tools configuration file."""
    return config_path("tools.json")


def _load_tools_config() -> dict[str, Any]:
    """Load tools configuration from file using config loader."""
    try:
        loader = get_config_loader()
        # A copy: handlers edit the result and then save it. Editing the loader's
        # own cache in place meant a rejected or failed save still changed what
        # every later request saw, and any caller that forgot to save leaked.
        return copy.deepcopy(loader.get_config("tools"))
    except FileNotFoundError:
        return {"version": "1.0", "tools": []}


def _save_tools_config(config: dict[str, Any]) -> None:
    """Save tools configuration to file."""
    config_path = _get_tools_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    get_config_loader().set_config("tools", copy.deepcopy(config))

    # Trigger reload in config loader
    try:
        loader = get_config_loader()
        loader._reload_single_file(config_path)
    except Exception as e:
        logger.warning(f"Failed to reload config in loader: {e}")


@router.post("", response_model=ToolResponse, status_code=status.HTTP_201_CREATED)
async def register_tool(
    request: Request,
    body: ToolRegisterRequest,
) -> ToolResponse:
    """
    Register a new tool.

    For function tools:
        - entrypoint is required (e.g., src.tools.calculator:calculate)

    For API tools:
        - settings.type must be 'api'
        - settings.api_url is required
        - entrypoint is auto-set to the API tool executor

    Args:
        request: FastAPI request object
        body: Tool registration request

    Returns:
        Registered tool information

    Requirements: 3.2, 4.1, 4.2
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Registering tool",
        request_id=request_id,
        tool_id=body.id,
    )

    try:
        # Load existing config
        config = _load_tools_config()

        # Check if tool already exists
        if any(t["id"] == body.id for t in config["tools"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "duplicate_tool_id",
                    "message": f"Tool already exists with ID: {body.id}",
                    "suggestion": "Use a different tool ID or update the existing tool",
                },
            )

        # Add new tool
        tool_dict = body.model_dump()
        config["tools"].append(tool_dict)

        # Save config
        _save_tools_config(config)

        # Register with tool registry if enabled. register_tool_from_entrypoint
        # branches internally on settings['type'] (function/api/mcp/database/gmail),
        # so every type becomes live immediately, not just function tools.
        tool_type = body.settings.get("type", "function")
        if body.enabled and body.entrypoint:
            try:
                tool_registry = get_tool_registry()
                tool_registry.register_tool_from_entrypoint(
                    tool_id=body.id,
                    entrypoint=body.entrypoint,
                    name=body.name,
                    description=body.description,
                    settings=body.settings,
                )
            except Exception as e:
                logger.warning(
                    "Failed to register tool with registry",
                    tool_id=body.id,
                    error=str(e),
                )

        logger.info(
            "Registered tool",
            request_id=request_id,
            tool_id=body.id,
            tool_type=tool_type,
        )

        return ToolResponse(**tool_dict)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to register tool",
            request_id=request_id,
            tool_id=body.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to register tool: {str(e)}",
        ) from e


@router.get("", response_model=list[ToolResponse])
async def list_tools(
    request: Request,
) -> list[ToolResponse]:
    """
    List all registered tools.

    Args:
        request: FastAPI request object

    Returns:
        List of tool configurations

    Requirements: 3.2, 4.1, 4.2
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Listing tools",
        request_id=request_id,
    )

    try:
        config = _load_tools_config()
        return [ToolResponse(**tool) for tool in config["tools"]]

    except Exception as e:
        logger.error(
            "Failed to list tools",
            request_id=request_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list tools: {str(e)}",
        ) from e


@router.get("/{tool_id}", response_model=ToolResponse)
async def get_tool(
    request: Request,
    tool_id: str,
) -> ToolResponse:
    """
    Get tool configuration by ID.

    Args:
        request: FastAPI request object
        tool_id: Tool identifier

    Returns:
        Tool configuration

    Requirements: 3.2, 4.1, 4.2
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Getting tool",
        request_id=request_id,
        tool_id=tool_id,
    )

    try:
        config = _load_tools_config()

        # Find tool
        tool = next((t for t in config["tools"] if t["id"] == tool_id), None)

        if tool is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tool not found: {tool_id}",
            )

        return ToolResponse(**tool)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get tool",
            request_id=request_id,
            tool_id=tool_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tool: {str(e)}",
        ) from e


@router.put("/{tool_id}", response_model=ToolResponse)
async def update_tool(
    request: Request,
    tool_id: str,
    body: ToolUpdateRequest,
) -> ToolResponse:
    """
    Update tool configuration.

    Args:
        request: FastAPI request object
        tool_id: Tool identifier
        body: Tool update request

    Returns:
        Updated tool configuration

    Requirements: 3.2, 4.1, 4.2
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Updating tool",
        request_id=request_id,
        tool_id=tool_id,
    )

    try:
        config = _load_tools_config()

        # Find tool
        tool_idx = next((i for i, t in enumerate(config["tools"]) if t["id"] == tool_id), None)

        if tool_idx is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tool not found: {tool_id}",
            )

        # Update tool
        tool = config["tools"][tool_idx]
        update_data = body.model_dump(exclude_unset=True)
        tool.update(update_data)

        # Save config
        _save_tools_config(config)

        # Reload tool registry if enabled status changed or entrypoint changed
        if "enabled" in update_data or "entrypoint" in update_data:
            try:
                tool_registry = get_tool_registry()
                tool_registry.reload_from_config()
            except Exception as e:
                logger.warning(
                    "Failed to reload tool registry",
                    error=str(e),
                )

        logger.info(
            "Updated tool",
            request_id=request_id,
            tool_id=tool_id,
        )

        return ToolResponse(**tool)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to update tool",
            request_id=request_id,
            tool_id=tool_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update tool: {str(e)}",
        ) from e


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(
    request: Request,
    tool_id: str,
) -> None:
    """
    Delete tool configuration.

    Args:
        request: FastAPI request object
        tool_id: Tool identifier

    Requirements: 3.2, 4.1, 4.2
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Deleting tool",
        request_id=request_id,
        tool_id=tool_id,
    )

    try:
        config = _load_tools_config()

        # Check if tool exists
        if not any(t["id"] == tool_id for t in config["tools"]):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tool not found: {tool_id}",
            )

        # Check for dependencies before deletion
        validator = get_validator()
        try:
            validator.validate_tool_deletion(tool_id)
        except DependencyError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "type": "dependency_error",
                    "message": str(e),
                    "dependents": e.dependents,
                },
            ) from e

        # Remove tool
        config["tools"] = [t for t in config["tools"] if t["id"] != tool_id]

        # Save config
        _save_tools_config(config)

        # Reload tool registry
        try:
            tool_registry = get_tool_registry()
            tool_registry.reload_from_config()
        except Exception as e:
            logger.warning(
                "Failed to reload tool registry",
                error=str(e),
            )

        logger.info(
            "Deleted tool",
            request_id=request_id,
            tool_id=tool_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to delete tool",
            request_id=request_id,
            tool_id=tool_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete tool: {str(e)}",
        ) from e


@router.post("/{tool_id}/execute", response_model=ToolExecutionResponse)
async def execute_tool(
    request: Request,
    tool_id: str,
    body: ToolExecutionRequest,
) -> ToolExecutionResponse:
    """
    Execute a tool directly.

    Args:
        request: FastAPI request object
        tool_id: Tool identifier
        body: Execution arguments

    Returns:
        Execution result
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Executing tool",
        request_id=request_id,
        tool_id=tool_id,
    )

    try:
        tool_registry = get_tool_registry()
        tool_def = tool_registry.get_tool(tool_id)

        if not tool_def:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tool not found: {tool_id}",
            )

        # Execute the tool function
        # Note: Context is already set by middleware if headers were provided
        if inspect.iscoroutinefunction(tool_def.function):
            result = await tool_def.function(**body.args)
        else:
            result = tool_def.function(**body.args)

        return ToolExecutionResponse(
            status="success",
            result=result,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Tool execution failed",
            request_id=request_id,
            tool_id=tool_id,
            error=str(e),
            exc_info=True,
        )
        return ToolExecutionResponse(
            status="error",
            result=None,
            error=str(e),
        )


class McpInspectRequest(BaseModel):
    """Request to connect to an MCP server and list its tools (works pre-save)."""

    settings: dict[str, Any] = Field(
        description="MCP tool settings (type/transport/command/url/...)"
    )


@router.post("/mcp/inspect")
async def inspect_mcp_server(request: Request, body: McpInspectRequest) -> dict[str, Any]:
    """Connect to an MCP server described by `settings`, list its tools, disconnect.

    Used by the studio's tool tester so users can verify a server (and discover
    its tool names for `tool_filter`) before saving the tool config.
    """
    request_id = getattr(request.state, "request_id", None)

    # Validate settings through the canonical schema first.
    settings = {**body.settings, "type": "mcp"}
    try:
        from src.config.tool_models import ToolConfig

        ToolConfig(
            id="mcp_inspect_probe",
            name="mcp_inspect_probe",
            description="inspect probe",
            settings=settings,
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    from src.tools.runtime_tool_factories import McpToolFactory

    factory = McpToolFactory("mcp_inspect_probe", "mcp_inspect_probe", "inspect probe", settings)
    started = time.perf_counter()
    try:
        # Adapter start is blocking (spawns subprocess / opens connection) — keep it
        # off the event loop.
        tools = await asyncio.to_thread(factory.inspect)
    except Exception as e:
        logger.warning("mcp_inspect_failed", request_id=request_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to connect to MCP server: {e}",
        ) from e

    return {
        "status": "connected",
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "tools": tools,
    }


@router.post("/import-swagger/preview", response_model=SwaggerPreviewResponse)
async def preview_swagger_import(
    request: Request,
    swagger_url: str,
) -> SwaggerPreviewResponse:
    """
    Preview endpoints from a Swagger/OpenAPI specification before importing.

    This endpoint fetches and parses the Swagger spec, then returns a preview
    of all available endpoints with duplicate detection against existing tools.

    Args:
        request: FastAPI request object
        swagger_url: URL to the Swagger/OpenAPI specification

    Returns:
        Preview of available endpoints and their generated tool IDs
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Previewing Swagger import",
        request_id=request_id,
        swagger_url=swagger_url,
    )

    try:
        # Load existing tools to check for duplicates
        config = _load_tools_config()
        existing_ids = {t["id"] for t in config["tools"]}

        # Parse the Swagger spec
        parser = SwaggerParser()
        parse_result = await parser.parse(swagger_url)

        # Build preview endpoints
        preview_endpoints = []
        duplicate_count = 0

        for endpoint in parse_result.endpoints:
            tool_id = sanitize_tool_id(endpoint.operation_id, endpoint.path, endpoint.method)
            is_duplicate = tool_id in existing_ids

            if is_duplicate:
                duplicate_count += 1

            preview_endpoints.append(
                SwaggerPreviewEndpoint(
                    operation_id=endpoint.operation_id,
                    path=endpoint.path,
                    method=endpoint.method,
                    summary=endpoint.summary,
                    description=endpoint.description[:200] + "..."
                    if len(endpoint.description) > 200
                    else endpoint.description,
                    tags=endpoint.tags,
                    generated_tool_id=tool_id,
                    is_duplicate=is_duplicate,
                )
            )

        return SwaggerPreviewResponse(
            title=parse_result.title,
            version=parse_result.version,
            description=parse_result.description,
            base_url=parse_result.base_url,
            openapi_version=parse_result.openapi_version,
            endpoints=preview_endpoints,
            total_endpoints=len(preview_endpoints),
            duplicate_count=duplicate_count,
            errors=parse_result.errors,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(
            "Failed to preview Swagger import",
            request_id=request_id,
            swagger_url=swagger_url,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse Swagger spec: {str(e)}",
        ) from e


@router.post("/import-swagger", response_model=SwaggerImportResult)
async def import_swagger_tools(
    request: Request,
    body: SwaggerImportRequest,
) -> SwaggerImportResult:
    """
    Import tools from a Swagger/OpenAPI specification.

    Parses the Swagger/OpenAPI spec and creates tool configurations for each endpoint.
    Supports both OpenAPI 2.0 (Swagger) and OpenAPI 3.0+ specifications.

    Duplicate tools (by ID) are automatically skipped.

    Args:
        request: FastAPI request object
        body: Swagger import request with URL and options

    Returns:
        Import result with counts and lists of imported/skipped tools
    """
    request_id = getattr(request.state, "request_id", None)

    logger.info(
        "Importing tools from Swagger",
        request_id=request_id,
        swagger_url=body.swagger_url,
        endpoint_filter=body.endpoint_filter,
    )

    try:
        # Load existing tools config
        config = _load_tools_config()
        existing_ids = {t["id"] for t in config["tools"]}

        # Parse and generate tools
        parser = SwaggerParser()
        parse_result = await parser.parse(body.swagger_url)

        tools, skipped = parser.generate_tool_configs(
            parse_result=parse_result,
            existing_tool_ids=existing_ids.copy(),  # Pass copy to track duplicates
            endpoint_filter=body.endpoint_filter,
            default_auth_type=body.auth_type,
            default_auth_env_var=body.auth_env_var,
            forward_user_context=body.forward_user_context,
            timeout=body.timeout,
        )

        # Import non-duplicate tools
        imported_tools = []
        errors = []

        for tool in tools:
            try:
                # Check again for duplicates (in case of race condition)
                if tool.id in existing_ids:
                    skipped.append(f"{tool.id} (already exists)")
                    continue

                # Create tool config
                tool_dict = {
                    "id": tool.id,
                    "name": tool.name,
                    "description": tool.description,
                    "entrypoint": tool.entrypoint,
                    "enabled": body.enabled,
                    "settings": tool.settings,
                }

                config["tools"].append(tool_dict)
                existing_ids.add(tool.id)
                imported_tools.append(tool.id)

            except Exception as e:
                errors.append(f"Failed to import {tool.id}: {str(e)}")

        # Save config if any tools were imported
        if imported_tools:
            _save_tools_config(config)

            # Reload tool registry
            try:
                tool_registry = get_tool_registry()
                tool_registry.reload_from_config()
            except Exception as e:
                logger.warning(
                    "Failed to reload tool registry after import",
                    error=str(e),
                )

        logger.info(
            "Swagger import completed",
            request_id=request_id,
            imported_count=len(imported_tools),
            skipped_count=len(skipped),
        )

        return SwaggerImportResult(
            success=True,
            imported_count=len(imported_tools),
            skipped_duplicates=skipped,
            imported_tools=imported_tools,
            errors=errors + parse_result.errors,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(
            "Failed to import Swagger tools",
            request_id=request_id,
            swagger_url=body.swagger_url,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import tools from Swagger: {str(e)}",
        ) from e
