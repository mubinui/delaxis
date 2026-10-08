"""Python function tool management endpoints.

Allows the AI Studio builder to save AI-generated Python code as executable
tool files in src/tools/generated/ and auto-register them in configs/tools.json.
"""

import json
import re
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.config.config_loader import get_config_loader
from src.config.paths import config_path

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/functions", tags=["functions"])

_GENERATED_DIR = Path("src/tools/generated")

# Only allow safe identifiers to prevent path traversal
_SAFE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class FunctionToolCreateRequest(BaseModel):
    id: str = Field(description="Snake_case unique ID (used as filename and tool ID)")
    name: str = Field(description="Python function name to expose to agents")
    description: str = Field(description="What this function does — agents read this")
    code: str = Field(description="Complete Python source code containing the function")


class FunctionToolResponse(BaseModel):
    id: str
    name: str
    description: str
    entrypoint: str
    file_path: str
    enabled: bool


class FunctionToolListResponse(BaseModel):
    functions: list[FunctionToolResponse]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_id(tool_id: str) -> None:
    if not _SAFE_ID_RE.match(tool_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid tool ID '{tool_id}'. Must match ^[a-z][a-z0-9_]{{0,63}}$",
        )


def _load_tools_config() -> dict[str, Any]:
    try:
        loader = get_config_loader()
        return loader.get_config("tools")
    except FileNotFoundError:
        return {"version": "1.0", "tools": []}


def _save_tools_config(config: dict[str, Any]) -> None:
    config_path("tools.json").parent.mkdir(parents=True, exist_ok=True)
    with open(config_path("tools.json"), "w") as f:
        json.dump(config, f, indent=2)
    try:
        loader = get_config_loader()
        loader._reload_single_file(config_path("tools.json"))
    except Exception as e:
        logger.warning("tools_config_reload_failed", error=str(e))


def _function_file_path(tool_id: str) -> Path:
    return _GENERATED_DIR / f"{tool_id}.py"


def _build_tool_entry(tool_id: str, name: str, description: str) -> dict[str, Any]:
    return {
        "id": tool_id,
        "name": name,
        "description": description,
        "entrypoint": f"src.tools.generated.{tool_id}:{name}",
        "enabled": True,
        "is_async": False,
        "settings": {"type": "python_function"},
        "version": 1,
        "_generated": True,
    }


def _sanitize_code(code: str, tool_id: str, name: str) -> str:
    """Basic safety validation — reject obviously dangerous patterns."""
    dangerous_patterns = [
        r"\bos\.system\b",
        r"\bsubprocess\b",
        r"\beval\b",
        r"\bexec\b",
        r"\b__import__\b",
        r"\bopen\s*\(",  # file writes outside allowed paths
        r"\bshutil\b",
        r"\bpickle\b",
    ]
    for pattern in dangerous_patterns:
        if re.search(pattern, code):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Generated code contains disallowed pattern '{pattern}'. Edit the code to remove it.",
            )
    return code


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=FunctionToolResponse, status_code=status.HTTP_201_CREATED)
async def create_function_tool(
    request: Request,
    body: FunctionToolCreateRequest,
) -> FunctionToolResponse:
    """
    Save AI-generated Python code as a tool file and register it in configs/tools.json.

    The function is written to src/tools/generated/{id}.py and registered with
    entrypoint `src.tools.generated.{id}:{name}` so agents can call it immediately.
    """
    _validate_id(body.id)

    # Safety check on the generated code
    safe_code = _sanitize_code(body.code, body.id, body.name)

    # Verify the named function exists in the code
    if not re.search(rf"\bdef\s+{re.escape(body.name)}\s*\(", safe_code):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Function '{body.name}' not found in the provided code.",
        )

    # Ensure generated dir exists with __init__.py
    _GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    init_file = _GENERATED_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text("# Auto-generated Python tool functions\n")

    # Check for duplicate tool ID
    config = _load_tools_config()
    if any(t["id"] == body.id for t in config.get("tools", [])):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A tool with ID '{body.id}' already exists. Delete it first or use a different ID.",
        )

    # Write the Python file
    file_path = _function_file_path(body.id)
    file_path.write_text(safe_code, encoding="utf-8")

    logger.info("function_tool_saved", tool_id=body.id, file=str(file_path))

    # Register in tools.json
    entry = _build_tool_entry(body.id, body.name, body.description)
    config.setdefault("tools", []).append(entry)
    _save_tools_config(config)

    logger.info("function_tool_registered", tool_id=body.id, entrypoint=entry["entrypoint"])

    return FunctionToolResponse(
        id=body.id,
        name=body.name,
        description=body.description,
        entrypoint=entry["entrypoint"],
        file_path=str(file_path),
        enabled=True,
    )


@router.get("", response_model=FunctionToolListResponse)
async def list_function_tools(request: Request) -> FunctionToolListResponse:
    """List all AI-generated Python function tools."""
    config = _load_tools_config()
    functions = [
        FunctionToolResponse(
            id=t["id"],
            name=t["name"],
            description=t.get("description", ""),
            entrypoint=t.get("entrypoint", ""),
            file_path=str(_function_file_path(t["id"])),
            enabled=t.get("enabled", True),
        )
        for t in config.get("tools", [])
        if t.get("_generated") is True
    ]
    return FunctionToolListResponse(functions=functions, total=len(functions))


@router.get("/{tool_id}", response_model=FunctionToolResponse)
async def get_function_tool(request: Request, tool_id: str) -> FunctionToolResponse:
    """Get metadata for a specific generated function tool."""
    _validate_id(tool_id)
    config = _load_tools_config()
    tool = next(
        (t for t in config.get("tools", []) if t["id"] == tool_id and t.get("_generated")),
        None,
    )
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Function tool '{tool_id}' not found.")
    return FunctionToolResponse(
        id=tool["id"],
        name=tool["name"],
        description=tool.get("description", ""),
        entrypoint=tool.get("entrypoint", ""),
        file_path=str(_function_file_path(tool_id)),
        enabled=tool.get("enabled", True),
    )


@router.get("/{tool_id}/source")
async def get_function_source(request: Request, tool_id: str) -> dict[str, Any]:
    """Return the Python source code for a generated function tool."""
    _validate_id(tool_id)
    file_path = _function_file_path(tool_id)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Source file for '{tool_id}' not found.")
    return {"tool_id": tool_id, "source": file_path.read_text(encoding="utf-8")}


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_function_tool(request: Request, tool_id: str) -> None:
    """Remove a generated function tool — deletes the .py file and unregisters it."""
    _validate_id(tool_id)

    config = _load_tools_config()
    original_count = len(config.get("tools", []))
    config["tools"] = [
        t for t in config.get("tools", []) if not (t["id"] == tool_id and t.get("_generated"))
    ]
    if len(config.get("tools", [])) == original_count:
        raise HTTPException(status_code=404, detail=f"Function tool '{tool_id}' not found.")

    _save_tools_config(config)

    file_path = _function_file_path(tool_id)
    if file_path.exists():
        file_path.unlink()

    logger.info("function_tool_deleted", tool_id=tool_id)
