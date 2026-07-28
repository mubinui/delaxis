"""Flash deployment endpoints — deployable chatbot pages served by the app itself.

Deployments are static single-file chat frontends generated from a workflow.
They are written under ``data/deployments/<id>/`` and served same-origin at
``/d/<id>/`` by this application — no extra processes or ports required.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, field_validator

from src.api.chatbot_page import (
    default_chatbot_html,
    ensure_config_contract,
    ensure_markdown_support,
    inject_runtime_config,
    normalize_theme,
    theme_presets,
    validate_page,
)

router = APIRouter(prefix="/api/v1/deployments", tags=["deployments"])

# Public router (no /api prefix) that serves the deployed chatbot pages
pages_router = APIRouter(tags=["deployments"])

# Anchored to the repo root so deployments resolve regardless of the CWD the
# app was started from; OAK_DATA_DIR overrides for containers/tests.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("OAK_DATA_DIR", str(_PROJECT_ROOT / "data")))
CONFIG_PATH = DATA_DIR / "deployments.json"
DEPLOYMENTS_DIR = DATA_DIR / "deployments"
DeploymentStatus = Literal["active", "error"]


class DeploymentCreateRequest(BaseModel):
    workflow_id: str
    name: str
    # Empty api_url means same-origin (the app that serves the page)
    api_url: str = ""
    trigger_id: str | None = None
    title: str = "AI Chatbot"
    theme: str = "midnight"
    greeting: str = "Hi, how can I help?"
    provider_id: str = "openrouter"
    model_id: str = "openai/gpt-oss-20b"
    auth_mode: str = "public"
    frontend_html: str | None = None
    frontend_source: str = "default"

    @field_validator("theme")
    @classmethod
    def _normalize_theme(cls, value: str) -> str:
        return normalize_theme(value)


class DeploymentResponse(BaseModel):
    id: str
    workflow_id: str
    name: str
    api_url: str = ""
    trigger_id: str | None = None
    title: str
    theme: str
    greeting: str
    provider_id: str
    model_id: str
    auth_mode: str
    status: DeploymentStatus
    url: str
    path: str
    created_at: str
    updated_at: str
    error: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "chatbot"


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"version": "1.0", "deployments": []}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _delete_deployment_path(path_value: str | None) -> None:
    if not path_value:
        return
    path = Path(path_value)
    # Only ever delete inside the deployments directory
    try:
        path.resolve().relative_to(DEPLOYMENTS_DIR.resolve())
    except ValueError:
        return
    if path.exists():
        shutil.rmtree(path)


def _render_deployment_html(body: DeploymentCreateRequest) -> tuple[str, list[str]]:
    """Render the final page for a deployment and collect validation warnings."""
    runtime_config = body.model_dump(exclude={"frontend_html"})
    if body.frontend_html:
        html = ensure_config_contract(body.frontend_html)
        html = inject_runtime_config(html, runtime_config)
        html = ensure_markdown_support(html)
    else:
        html = default_chatbot_html(
            title=body.title,
            greeting=body.greeting,
            workflow_id=body.workflow_id,
            provider_id=body.provider_id,
            model_id=body.model_id,
            theme=body.theme,
            config=runtime_config,
        )
    return html, validate_page(html)


def _write_deployment(deployment_id: str, body: DeploymentCreateRequest) -> Path:
    path = DEPLOYMENTS_DIR / deployment_id
    path.mkdir(parents=True, exist_ok=True)
    html, _warnings = _render_deployment_html(body)
    (path / "index.html").write_text(html, encoding="utf-8")
    (path / "deployment.json").write_text(json.dumps(body.model_dump(exclude={"frontend_html"}), indent=2), encoding="utf-8")
    return path


@router.get("", response_model=list[DeploymentResponse])
async def list_deployments() -> list[DeploymentResponse]:
    config = _load_config()
    return [DeploymentResponse(**deployment) for deployment in config.get("deployments", [])]


@router.get("/themes")
async def list_deployment_themes() -> list[dict[str, Any]]:
    """Theme presets available for deployed chatbot pages."""
    return theme_presets()


@router.post("/preview")
async def preview_deployment(body: DeploymentCreateRequest) -> dict[str, Any]:
    deployment_id = _slug(body.name)
    html, warnings = _render_deployment_html(body)
    return {
        "url": f"/d/{deployment_id}/",
        "path": str(DEPLOYMENTS_DIR / deployment_id),
        "warnings": warnings,
        "html": html,
    }


@router.post("/flash", response_model=DeploymentResponse, status_code=status.HTTP_201_CREATED)
async def flash_deploy(body: DeploymentCreateRequest) -> DeploymentResponse:
    config = _load_config()
    deployment_id = _slug(body.name)
    now = _now()
    record: dict[str, Any] = {
        **body.model_dump(exclude={"frontend_html"}),
        "id": deployment_id,
        "status": "active",
        "url": f"/d/{deployment_id}/",
        "path": str(DEPLOYMENTS_DIR / deployment_id),
        "created_at": now,
        "updated_at": now,
        "error": None,
    }

    error: Exception | None = None
    try:
        _write_deployment(deployment_id, body)
    except Exception as exc:
        error = exc
        record["status"] = "error"
        record["error"] = str(exc)

    config["deployments"] = [
        deployment for deployment in config.get("deployments", []) if deployment["id"] != deployment_id
    ]
    config.setdefault("deployments", []).append(record)
    _save_config(config)
    if error is not None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Deployment generation failed: {error}",
        )
    return DeploymentResponse(**record)


@router.delete("/{deployment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deployment(deployment_id: str) -> None:
    config = _load_config()
    deployments = config.get("deployments", [])
    record = next((deployment for deployment in deployments if deployment["id"] == deployment_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Deployment not found: {deployment_id}")

    config["deployments"] = [
        deployment for deployment in deployments if deployment["id"] != deployment_id
    ]
    _save_config(config)
    _delete_deployment_path(record.get("path"))


@pages_router.get("/d/{deployment_id}", include_in_schema=False)
async def redirect_deployment_page(deployment_id: str) -> RedirectResponse:
    """Redirect to the trailing-slash URL so relative links resolve correctly."""
    return RedirectResponse(url=f"/d/{deployment_id}/", status_code=307)


@pages_router.get("/d/{deployment_id}/", include_in_schema=False)
async def serve_deployment_page(deployment_id: str) -> FileResponse:
    """Serve a deployed chatbot page same-origin."""
    index = DEPLOYMENTS_DIR / deployment_id / "index.html"
    try:
        index.resolve().relative_to(DEPLOYMENTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Deployment not found")
    if not index.exists():
        raise HTTPException(status_code=404, detail=f"Deployment not found: {deployment_id}")
    return FileResponse(index, media_type="text/html")
