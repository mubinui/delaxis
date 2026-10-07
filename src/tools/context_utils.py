"""Utilities for tool context management."""

import json
from contextvars import ContextVar
from typing import Any

# Use ContextVar with copy_context for async propagation
# This is the recommended approach for asyncio
_tool_username: ContextVar[str | None] = ContextVar("tool_username", default=None)
_tool_roles: ContextVar[list[str] | None] = ContextVar("tool_roles", default=None)
_tool_raw_token: ContextVar[str | None] = ContextVar("tool_raw_token", default=None)

# Also maintain a simple module-level fallback (for sync tool execution)
_global_context: dict[str, Any] = {
    "username": None,
    "roles": None,
    "raw_token": None,
}


def set_tool_execution_context(
    username: str | None, roles: list[str] | None, raw_token: str | None = None
) -> None:
    """
    Set user context for tool execution.

    This should be called before agent execution begins to ensure
    tools have access to user context.

    Args:
        username: Username for x-client-username header
        roles: Roles for x-client-ref header
        raw_token: Raw JWT token for service calls
    """
    # Set ContextVar (for async propagation)
    _tool_username.set(username)
    _tool_roles.set(roles)
    _tool_raw_token.set(raw_token)

    # Also set global fallback
    _global_context["username"] = username
    _global_context["roles"] = roles
    _global_context["raw_token"] = raw_token


def clear_tool_execution_context() -> None:
    """Clear the tool execution context after agent execution completes."""
    _tool_username.set(None)
    _tool_roles.set(None)
    _tool_raw_token.set(None)

    _global_context["username"] = None
    _global_context["roles"] = None
    _global_context["raw_token"] = None


def get_user_context_headers() -> dict[str, str]:
    """
    Get headers containing current user context.

    Returns:
        Dict with x-client-ref and x-client-username headers if user context exists.
        x-client-ref contains roles as JSON array.
    """
    headers = {}
    from src.api.context import get_request_user  # local import to avoid circular dependency

    current_user = get_request_user()

    if current_user:
        if current_user.username:
            headers["x-client-username"] = current_user.username

        # Use roles list if available, otherwise fall back to single role
        if current_user.roles:
            headers["x-client-ref"] = json.dumps(current_user.roles)
        elif current_user.role:
            headers["x-client-ref"] = json.dumps([current_user.role.value])

    return headers


def get_user_context_info() -> dict[str, str | list[str] | None]:
    """
    Get current user context information.

    Tries multiple sources in order:
    1. ContextVar (async-safe, set before agent execution)
    2. Global module-level fallback
    3. Request context (ContextVar from middleware)

    Returns:
        Dict with username, roles, user_id, and raw_token.
    """
    # First try ContextVar (async-propagated)
    ctx_username = _tool_username.get()
    ctx_roles = _tool_roles.get()
    ctx_token = _tool_raw_token.get()

    if ctx_username or ctx_roles:
        return {
            "username": ctx_username,
            "roles": ctx_roles if ctx_roles else [],
            "user_id": None,
            "raw_token": ctx_token,
        }

    # Try global fallback
    if _global_context.get("username") or _global_context.get("roles"):
        return {
            "username": _global_context.get("username"),
            "roles": _global_context.get("roles") or [],
            "user_id": None,
            "raw_token": _global_context.get("raw_token"),
        }

    # Fall back to request context (ContextVar from middleware)
    from src.api.context import get_request_user  # local import to avoid circular dependency

    current_user = get_request_user()

    if current_user:
        # Use roles list if available, otherwise fall back to single role
        roles = (
            current_user.roles
            if current_user.roles
            else ([current_user.role.value] if current_user.role else [])
        )
        return {
            "username": current_user.username,
            "roles": roles,
            "user_id": str(current_user.user_id) if current_user.user_id else None,
            "raw_token": current_user.raw_token,  # JWT token for external service calls
        }

    return {
        "username": None,
        "roles": [],
        "user_id": None,
        "raw_token": None,
    }
