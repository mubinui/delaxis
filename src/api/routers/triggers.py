"""Trigger management and public webhook invocation endpoints."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.api.test_models import WorkflowExecuteRequest
from src.core.workflow_test_runner import get_test_runner
from src.utils.jsonio import as_object

router = APIRouter(prefix="/api/v1/triggers", tags=["triggers"])
webhook_router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

CONFIG_PATH = Path("configs") / "triggers.json"
TriggerType = Literal["chat", "webhook", "manual"]
AuthMode = Literal["public", "api_key", "jwt"]


class TriggerConfig(BaseModel):
    id: str
    workflow_id: str
    type: TriggerType
    enabled: bool = True
    name: str
    auth_mode: AuthMode = "public"
    provider_id: str = "openrouter"
    model_id: str = "openai/gpt-oss-20b"
    greeting: str = "Hi, how can I help?"
    public_slug: str | None = None
    secret: str | None = None
    allowed_origins: list[str] = Field(default_factory=list)
    input_mapping: dict[str, Any] = Field(default_factory=dict)
    response_mapping: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class TriggerCreateRequest(BaseModel):
    workflow_id: str
    type: TriggerType
    name: str | None = None
    auth_mode: AuthMode = "public"
    provider_id: str = "openrouter"
    model_id: str = "openai/gpt-oss-20b"
    greeting: str = "Hi, how can I help?"
    public_slug: str | None = None
    allowed_origins: list[str] = Field(default_factory=list)
    input_mapping: dict[str, Any] = Field(default_factory=dict)
    response_mapping: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TriggerUpdateRequest(BaseModel):
    enabled: bool | None = None
    name: str | None = None
    auth_mode: AuthMode | None = None
    provider_id: str | None = None
    model_id: str | None = None
    greeting: str | None = None
    public_slug: str | None = None
    rotate_secret: bool = False
    allowed_origins: list[str] | None = None
    input_mapping: dict[str, Any] | None = None
    response_mapping: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or secrets.token_hex(4)


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"version": "1.0", "triggers": []}
    return as_object(json.loads(CONFIG_PATH.read_text(encoding="utf-8")), str(CONFIG_PATH))


def _save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _find_trigger(config: dict[str, Any], trigger_id: str) -> dict[str, Any] | None:
    return next(
        (trigger for trigger in config.get("triggers", []) if trigger["id"] == trigger_id), None
    )


@router.get("", response_model=list[TriggerConfig])
async def list_triggers(workflow_id: str | None = None) -> list[TriggerConfig]:
    config = _load_config()
    triggers = config.get("triggers", [])
    if workflow_id:
        triggers = [trigger for trigger in triggers if trigger["workflow_id"] == workflow_id]
    return [TriggerConfig(**trigger) for trigger in triggers]


@router.post("", response_model=TriggerConfig, status_code=status.HTTP_201_CREATED)
async def create_trigger(body: TriggerCreateRequest) -> TriggerConfig:
    config = _load_config()
    trigger_id = f"{body.type}_{_slug(body.workflow_id)}_{secrets.token_hex(3)}"
    public_slug = body.public_slug or (
        f"{_slug(body.workflow_id)}-{secrets.token_hex(3)}" if body.type == "webhook" else None
    )
    now = _now()
    trigger = TriggerConfig(
        id=trigger_id,
        workflow_id=body.workflow_id,
        type=body.type,
        name=body.name or f"{body.type.title()} trigger",
        auth_mode=body.auth_mode,
        provider_id=body.provider_id,
        model_id=body.model_id,
        greeting=body.greeting,
        public_slug=public_slug,
        secret=secrets.token_urlsafe(24)
        if body.auth_mode == "api_key" or body.type == "webhook"
        else None,
        allowed_origins=body.allowed_origins,
        input_mapping=body.input_mapping,
        response_mapping=body.response_mapping,
        metadata=body.metadata,
        created_at=now,
        updated_at=now,
    ).model_dump()
    config.setdefault("triggers", []).append(trigger)
    _save_config(config)
    return TriggerConfig(**trigger)


@router.put("/{trigger_id}", response_model=TriggerConfig)
async def update_trigger(trigger_id: str, body: TriggerUpdateRequest) -> TriggerConfig:
    config = _load_config()
    trigger = _find_trigger(config, trigger_id)
    if trigger is None:
        raise HTTPException(status_code=404, detail=f"Trigger not found: {trigger_id}")

    updates = body.model_dump(exclude_unset=True)
    rotate_secret = bool(updates.pop("rotate_secret", False))
    for key, value in updates.items():
        if value is not None:
            trigger[key] = value
    if rotate_secret:
        trigger["secret"] = secrets.token_urlsafe(24)
    trigger["updated_at"] = _now()
    _save_config(config)
    return TriggerConfig(**trigger)


@router.delete("/{trigger_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trigger(trigger_id: str) -> None:
    config = _load_config()
    before = len(config.get("triggers", []))
    config["triggers"] = [
        trigger for trigger in config.get("triggers", []) if trigger["id"] != trigger_id
    ]
    if len(config["triggers"]) == before:
        raise HTTPException(status_code=404, detail=f"Trigger not found: {trigger_id}")
    _save_config(config)


@webhook_router.post("/{public_slug}")
async def invoke_webhook(public_slug: str, request: Request) -> dict[str, Any]:
    config = _load_config()
    trigger = next(
        (
            candidate
            for candidate in config.get("triggers", [])
            if candidate.get("public_slug") == public_slug and candidate.get("type") == "webhook"
        ),
        None,
    )
    if trigger is None or not trigger.get("enabled", True):
        raise HTTPException(status_code=404, detail="Webhook not found")

    secret = trigger.get("secret")
    if trigger.get("auth_mode") == "api_key" and secret:
        supplied = request.headers.get("x-trigger-secret") or request.query_params.get("secret")
        if supplied != secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    payload = await request.json()
    message = (
        payload.get("message") or payload.get("text") or payload.get("query") or json.dumps(payload)
    )
    runner = get_test_runner()
    result = await runner.execute_workflow(
        trigger["workflow_id"],
        WorkflowExecuteRequest(message=message, metadata={"trigger": trigger, "payload": payload}),
    )
    return {
        "trigger_id": trigger["id"],
        "workflow_id": trigger["workflow_id"],
        "success": result.success,
        "response": result.response,
        "trace": result.execution_trace,
    }
