"""What a connector declares, and what one of its actions receives.

A connector is data: its auth, its options and its actions. The catalogue
endpoint serves these declarations so the Studio can render a connector's
palette tile and inspector form without knowing it; the tool factory turns
the actions a node ticks into agent tools with real argument schemas.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, cast

import httpx
from pydantic import BaseModel, Field, ValidationError, create_model

ParamType = Literal["string", "integer", "boolean", "array", "object"]
ActionKind = Literal["read", "write"]
AuthKind = Literal["token", "oauth"]

_PY_TYPES: dict[str, Any] = {
    "string": str,
    "integer": int,
    "boolean": bool,
    "array": list[Any],
    "object": dict[str, Any],
}


class ConnectorError(Exception):
    """A failure to show as is: the remote's reason, or what the user should fix."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Param:
    name: str
    type: ParamType
    description: str
    required: bool = True
    default: Any = None
    enum: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ConnectionSecrets:
    """A connection as an action needs it: where to call and with what."""

    base_url: str | None
    username: str | None
    token: str
    account_label: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectorContext:
    """Everything one action call gets: the connection, the node's options, a transport."""

    secrets: ConnectionSecrets
    options: dict[str, Any]
    # Tests pass an httpx.MockTransport; production leaves it None.
    transport: httpx.BaseTransport | None = None

    def option(self, key: str, default: Any = None) -> Any:
        """The node's value, else the connection's, else ``default``. Empty counts as unset."""
        for source in (self.options, self.secrets.options):
            value = source.get(key)
            if value not in (None, ""):
                return value
        return default


@dataclass(frozen=True)
class Action:
    id: str
    name: str
    kind: ActionKind
    description: str
    params: tuple[Param, ...]
    run: Callable[[ConnectorContext, dict[str, Any]], Any]


@dataclass(frozen=True)
class AuthSpec:
    kind: AuthKind
    base_url: bool = False
    base_url_default: str | None = None
    base_url_label: str = "Base URL"
    # Shown as a field when not None (Jira Cloud's account email).
    username_label: str | None = None
    username_required: bool = False
    token_label: str = "Token"
    token_help: str = ""
    # For kind == "oauth": the API path that returns {"auth_url": ...}.
    oauth_start: str | None = None


@dataclass(frozen=True)
class OptionField:
    key: str
    label: str
    help: str = ""


@dataclass(frozen=True)
class VerifyResult:
    account_label: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Connector:
    id: str
    name: str
    icon: str
    description: str
    auth: AuthSpec
    actions: tuple[Action, ...]
    options: tuple[OptionField, ...] = ()
    verify: Callable[[ConnectorContext], VerifyResult] | None = None

    def action(self, action_id: str) -> Action:
        for action in self.actions:
            if action.id == action_id:
                return action
        raise KeyError(f"{self.name} has no action '{action_id}'")


def args_model(connector_id: str, action: Action) -> type[BaseModel]:
    """A pydantic model for an action's parameters: the agent tool's argument schema."""
    fields: dict[str, Any] = {}
    for param in action.params:
        py_type: Any = _PY_TYPES[param.type]
        if param.enum:
            py_type = Literal[param.enum]
        if param.required:
            fields[param.name] = (py_type, Field(description=param.description))
        else:
            fields[param.name] = (
                py_type | None,
                Field(default=param.default, description=param.description),
            )
    model = create_model(f"{connector_id}_{action.id}_args", **fields)
    return cast(type[BaseModel], model)


def validate_args(connector_id: str, action: Action, args: dict[str, Any]) -> dict[str, Any]:
    """Coerce an action's arguments, or say which field is wrong."""
    try:
        parsed = args_model(connector_id, action).model_validate(args)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConnectorError(f"Invalid arguments for {action.id}: {problems}") from exc
    return parsed.model_dump(exclude_none=True)


def catalogue_entry(connector: Connector) -> dict[str, Any]:
    """The connector as the Studio sees it. No callables, no secrets."""
    auth = connector.auth
    return {
        "id": connector.id,
        "name": connector.name,
        "icon": connector.icon,
        "description": connector.description,
        "auth": {
            "kind": auth.kind,
            "base_url": auth.base_url,
            "base_url_default": auth.base_url_default,
            "base_url_label": auth.base_url_label,
            "username_label": auth.username_label,
            "username_required": auth.username_required,
            "token_label": auth.token_label,
            "token_help": auth.token_help,
            "oauth_start": auth.oauth_start,
        },
        "options": [
            {"key": option.key, "label": option.label, "help": option.help}
            for option in connector.options
        ],
        "actions": [
            {
                "id": action.id,
                "name": action.name,
                "kind": action.kind,
                "description": action.description,
                "params": [
                    {
                        "name": param.name,
                        "type": param.type,
                        "description": param.description,
                        "required": param.required,
                        "default": param.default,
                        "enum": list(param.enum) if param.enum else None,
                    }
                    for param in action.params
                ],
            }
            for action in connector.actions
        ],
    }
