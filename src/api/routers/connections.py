"""Connectors and connections: the catalogue, accounts, and running one action.

The catalogue is what the Studio renders palette tiles and inspector forms
from. A connection is only saved after the connector's verifier accepted its
credentials, so a saved connection is known to have worked at least once.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from src.audit_logging import get_logger
from src.connectors.base import (
    ConnectionSecrets,
    ConnectorContext,
    ConnectorError,
    catalogue_entry,
    validate_args,
)
from src.connectors.registry import all_connectors, get_connector
from src.connectors.store import ConnectionStore

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


class ConnectionCreate(BaseModel):
    connector: str
    base_url: str | None = None
    username: str | None = None
    token: str = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)


class ActionRun(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


def normalise_base_url(
    value: str | None, default: str | None, required: bool, label: str = "Base URL"
) -> str | None:
    """Trim a pasted URL, fall back to the default, and insist on a scheme."""
    url = (value or "").strip() or (default or "")
    if not url:
        if required:
            raise ValueError(f"{label} is required.")
        return None
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"{label} must start with http:// or https:// (got {url}).")
    return url.rstrip("/")


def _audit(action: str, resource: str, detail: dict[str, Any]) -> None:
    try:
        from src.tools.audit_trail import append_audit_entry

        append_audit_entry(action=action, category="config", resource=resource, detail=detail)
    except Exception as exc:  # noqa: BLE001 - auditing must not block the change
        logger.warning("connection_audit_failed", action=action, error=str(exc))


@router.get("/connectors")
async def list_connectors() -> dict[str, Any]:
    return {"connectors": [catalogue_entry(connector) for connector in all_connectors()]}


@router.get("/connections")
async def list_connections(connector: str | None = None) -> dict[str, Any]:
    connections = await asyncio.to_thread(ConnectionStore().list_connections, connector)
    return {"connections": [connection.to_dict() for connection in connections]}


@router.post("/connections", status_code=status.HTTP_201_CREATED)
async def create_connection(body: ConnectionCreate) -> dict[str, Any]:
    connector = get_connector(body.connector)
    if connector is None:
        raise HTTPException(status_code=404, detail=f"Unknown connector: {body.connector}")
    if connector.auth.kind == "oauth":
        raise HTTPException(
            status_code=400,
            detail=f"Connect {connector.name} through its sign-in button, not a pasted token.",
        )
    try:
        base_url = normalise_base_url(
            body.base_url,
            connector.auth.base_url_default,
            required=connector.auth.base_url,
            label=connector.auth.base_url_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    username = (body.username or "").strip() or None
    if connector.auth.username_required and not username:
        raise HTTPException(status_code=400, detail=f"{connector.auth.username_label} is required.")

    secrets = ConnectionSecrets(
        base_url=base_url, username=username, token=body.token.strip(), options=dict(body.options)
    )
    account_label = connector.name
    options = dict(body.options)
    if connector.verify is not None:
        try:
            verified = await asyncio.to_thread(connector.verify, ConnectorContext(secrets, {}))
        except ConnectorError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        account_label = verified.account_label
        options.update(verified.options)

    connection = await asyncio.to_thread(
        ConnectionStore().create,
        connector=connector.id,
        base_url=base_url,
        username=username,
        token=secrets.token,
        account_label=account_label,
        options=options,
    )
    _audit(
        "connection.created",
        f"connection:{connection.id}",
        {"connector": connector.id, "account": account_label},
    )
    return connection.to_dict()


@router.post("/connections/{connection_id}/test")
async def test_connection(connection_id: str) -> dict[str, Any]:
    store = ConnectionStore()
    connection = await asyncio.to_thread(store.get, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    connector = get_connector(connection.connector)
    secrets = await asyncio.to_thread(store.secrets, connection_id)
    if connector is None or secrets is None or connector.verify is None:
        return {"ok": True, "account_label": connection.account_label, "error": None}
    try:
        verified = await asyncio.to_thread(connector.verify, ConnectorContext(secrets, {}))
    except ConnectorError as exc:
        await asyncio.to_thread(store.record_test, connection_id, ok=False, error=str(exc))
        return {"ok": False, "account_label": connection.account_label, "error": str(exc)}
    await asyncio.to_thread(
        store.record_test, connection_id, ok=True, account_label=verified.account_label
    )
    return {"ok": True, "account_label": verified.account_label, "error": None}


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(connection_id: str) -> Response:
    if not await asyncio.to_thread(ConnectionStore().delete, connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    _audit("connection.deleted", f"connection:{connection_id}", {})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/connections/{connection_id}/actions/{action_id}")
async def run_action(
    connection_id: str, action_id: str, body: ActionRun | None = None
) -> dict[str, Any]:
    """Run one action now, for the inspector's Test. Writes act on the real system."""
    store = ConnectionStore()
    connection = await asyncio.to_thread(store.get, connection_id)
    secrets = await asyncio.to_thread(store.secrets, connection_id) if connection else None
    connector = get_connector(connection.connector) if connection else None
    if connection is None or secrets is None or connector is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        action = connector.action(action_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    request_body = body or ActionRun()
    try:
        args = validate_args(connector.id, action, request_body.args)
        result = await asyncio.to_thread(
            action.run, ConnectorContext(secrets, request_body.options), args
        )
    except ConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"result": result}
