"""Flash deployment endpoints — deployable chatbot pages served by the app itself.

Deployments are static single-file chat frontends generated from a workflow.
They are written under ``data/deployments/<id>/`` and served same-origin at
``/d/<id>/`` by this application — no extra processes or ports required.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator

from src.api.chatbot_page import (
    default_chatbot_html,
    embed_script,
    ensure_config_contract,
    ensure_markdown_support,
    ensure_voice_support,
    inject_runtime_config,
    normalize_theme,
    theme_presets,
    validate_page,
)
from src.config.env_compat import env

router = APIRouter(prefix="/api/v1/deployments", tags=["deployments"])

# Public router (no /api prefix) that serves the deployed chatbot pages
pages_router = APIRouter(tags=["deployments"])

# Anchored to the repo root so deployments resolve regardless of the CWD the
# app was started from; DELAXIS_DATA_DIR overrides for containers/tests.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(env("DELAXIS_DATA_DIR", str(_PROJECT_ROOT / "data")) or str(_PROJECT_ROOT / "data"))
CONFIG_PATH = DATA_DIR / "deployments.json"
DEPLOYMENTS_DIR = DATA_DIR / "deployments"
DeploymentStatus = Literal["active", "error"]


class DeploymentVoiceConfig(BaseModel):
    """Live voice settings for a deployment.

    Only ``enabled`` and ``greeting_spoken`` are safe to publish to the page —
    see ``_public_voice_config``.
    """

    enabled: bool = False
    provider_id: str = "gemini"
    # Empty means the provider's configured default; validated against the
    # provider's live allow-list when a session is opened.
    model: str = ""
    voice_name: str = ""
    # Empty means derive from the workflow's entry agent.
    system_prompt: str = ""
    greeting_spoken: bool = True
    max_session_seconds: int = 300


class DeploymentCreateRequest(BaseModel):
    workflow_id: str
    name: str
    # Empty api_url means same-origin (the app that serves the page)
    api_url: str = ""
    trigger_id: str | None = None
    title: str = "AI Chatbot"
    theme: str = "midnight"
    greeting: str = "Hi, how can I help?"
    # Starter prompts offered on an empty conversation.
    suggestions: list[str] = Field(default_factory=list)
    provider_id: str = "openrouter"
    model_id: str = "openai/gpt-oss-20b"
    auth_mode: str = "public"
    voice: DeploymentVoiceConfig = Field(default_factory=DeploymentVoiceConfig)
    frontend_html: str | None = None
    frontend_source: str = "default"

    @field_validator("theme")
    @classmethod
    def _normalize_theme(cls, value: str) -> str:
        return normalize_theme(value)

    @field_validator("suggestions")
    @classmethod
    def _trim_suggestions(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()][:4]


class DeploymentResponse(BaseModel):
    id: str
    workflow_id: str
    name: str
    api_url: str = ""
    trigger_id: str | None = None
    title: str
    theme: str
    greeting: str
    suggestions: list[str] = Field(default_factory=list)
    provider_id: str
    model_id: str
    auth_mode: str
    voice: DeploymentVoiceConfig = Field(default_factory=DeploymentVoiceConfig)
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


def _public_voice_config(voice: DeploymentVoiceConfig) -> dict[str, Any]:
    """The only voice fields safe to embed in the served page.

    ``window.CHATBOT_CONFIG`` is readable and editable by every visitor, so the
    model, the voice name and the system prompt must never appear there — the
    page would become a free, promptable handle on a billed realtime model. The
    page only needs to know whether to show a mic; everything else is resolved
    server-side from the deployment record, exactly as with the chat model.
    """
    return {"enabled": bool(voice.enabled), "greeting_spoken": bool(voice.greeting_spoken)}


def _render_deployment_html(body: DeploymentCreateRequest) -> tuple[str, list[str]]:
    """Render the final page for a deployment and collect validation warnings."""
    runtime_config = body.model_dump(exclude={"frontend_html"})
    runtime_config["voice"] = _public_voice_config(body.voice)
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
            voice_enabled=body.voice.enabled,
        )
    if body.voice.enabled:
        html = ensure_voice_support(html)
    return html, validate_page(html, voice_enabled=body.voice.enabled)


def _write_deployment(deployment_id: str, body: DeploymentCreateRequest) -> Path:
    path = DEPLOYMENTS_DIR / deployment_id
    path.mkdir(parents=True, exist_ok=True)
    html, _warnings = _render_deployment_html(body)
    (path / "index.html").write_text(html, encoding="utf-8")
    (path / "deployment.json").write_text(json.dumps(body.model_dump(exclude={"frontend_html"}), indent=2), encoding="utf-8")
    return path


def deployment_model_override(deployment_ref: str) -> dict[str, str] | None:
    """Model settings a deployment pins, resolved server-side.

    The generated page also sends provider_id/model_id in its message metadata,
    but that JS is editable by anyone who opens a public deployment, so it is
    never trusted for routing. The deployment record is the only authority.
    """
    if not deployment_ref:
        return None
    deployment_id = _slug(str(deployment_ref))
    try:
        config = _load_config()
    except (OSError, json.JSONDecodeError):
        return None
    record = next(
        (d for d in config.get("deployments", []) if d.get("id") == deployment_id), None
    )
    if record is None:
        return None
    override: dict[str, str] = {}
    if record.get("provider_id"):
        override["provider_id"] = str(record["provider_id"])
    if record.get("model_id"):
        override["model"] = str(record["model_id"])
    return override or None


def deployment_voice_config(deployment_ref: str) -> DeploymentVoiceConfig | None:
    """The voice settings a deployment pins, resolved server-side.

    Same reasoning as ``deployment_model_override``: the served page carries only
    the public subset (see ``_public_voice_config``), and its JS is editable by
    any visitor, so the deployment record is the only authority for the realtime
    model, voice and persona.
    """
    if not deployment_ref:
        return None
    deployment_id = _slug(str(deployment_ref))
    try:
        config = _load_config()
    except (OSError, json.JSONDecodeError):
        return None
    record = next(
        (d for d in config.get("deployments", []) if d.get("id") == deployment_id), None
    )
    if record is None:
        return None
    voice = record.get("voice")
    if not isinstance(voice, dict):
        return None
    try:
        return DeploymentVoiceConfig(**voice)
    except Exception:
        return None


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


def _deployment_record(deployment_id: str) -> dict[str, Any]:
    try:
        config = _load_config()
    except (OSError, json.JSONDecodeError):
        config = {"deployments": []}
    record = next((d for d in config.get("deployments", []) if d.get("id") == deployment_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Deployment not found: {deployment_id}")
    return record


@router.get("/{deployment_id}/integration")
async def deployment_integration(deployment_id: str, request: Request) -> dict[str, Any]:
    """Ready-to-paste snippets for putting this chatbot into another product.

    The origin is taken from the request so the snippets are correct behind a
    proxy or a custom domain, instead of hardcoding localhost.
    """
    record = _deployment_record(deployment_id)
    origin = str(request.base_url).rstrip("/")
    page_url = f"{origin}/d/{deployment_id}/"
    return {
        "id": deployment_id,
        "url": page_url,
        "embed_script_url": f"{page_url}embed.js",
        "workflow_id": record.get("workflow_id"),
        "auth_mode": record.get("auth_mode", "public"),
        "snippets": {
            "widget": f'<script src="{page_url}embed.js" defer></script>',
            "widget_options": (
                f'<script src="{page_url}embed.js" defer\n'
                '        data-position="right"\n'
                f'        data-label="{record.get("title", "Chat")}"\n'
                '        data-width="400" data-height="620"></script>'
            ),
            "iframe": (
                f'<iframe src="{page_url}" title="{record.get("title", "Chatbot")}"\n'
                '        style="width:100%;height:640px;border:0;border-radius:12px"\n'
                '        allow="clipboard-write"></iframe>'
            ),
            "link": page_url,
            "curl": (
                f"# 1. open a session\n"
                f'SESSION=$(curl -s -X POST {origin}/api/v1/sessions \\\n'
                f"  -H \"Content-Type: application/json\" \\\n"
                f"  -d '{{\"workflow_id\": \"{record.get('workflow_id')}\", \"user_id\": \"alice\"}}' \\\n"
                f"  | python -c \"import sys,json; print(json.load(sys.stdin)['session_id'])\")\n\n"
                f"# 2. send a message (repeat for each turn)\n"
                f'curl -s -X POST {origin}/api/v1/sessions/$SESSION/messages \\\n'
                f"  -H \"Content-Type: application/json\" \\\n"
                f"  -d '{{\"message\": \"Hello\"}}'"
            ),
        },
    }


@pages_router.get("/d/{deployment_id}/embed.js", include_in_schema=False)
async def serve_embed_script(deployment_id: str, request: Request) -> Response:
    """The floating-launcher widget for this deployment."""
    record = _deployment_record(deployment_id)
    script = embed_script(
        deployment_id=deployment_id,
        title=str(record.get("title") or "Chat"),
        theme=str(record.get("theme") or "midnight"),
        origin=str(request.base_url).rstrip("/"),
    )
    return Response(
        content=script,
        media_type="application/javascript",
        # Embedded on third-party pages by design, so it must be cross-origin readable.
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"},
    )


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
