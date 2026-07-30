"""CrewAI runtime configurability endpoints."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.config.settings import get_settings

router = APIRouter(prefix="/api/v1/crewai", tags=["crewai"])


class CrewAIMemorySettings(BaseModel):
    """Memory settings used by crews and flows."""

    enabled: bool = True
    storage_dir: str = "./.crewai"
    retention: str = "session"


class CrewAIKnowledgeSettings(BaseModel):
    """Knowledge retrieval settings."""

    enabled: bool = True
    collections: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=50)


class CrewAITracingSettings(BaseModel):
    """Observability settings for CrewAI events."""

    enabled: bool = True
    amp_enabled: bool = False
    event_listeners: list[str] = Field(default_factory=lambda: ["crew", "agent", "task", "tool", "llm", "memory"])


class CrewAIGuardrailSettings(BaseModel):
    """Guardrail and output settings."""

    enabled: bool = True
    human_review: bool = False
    output_schema: str = "text"


class CrewAIMcpSettings(BaseModel):
    """MCP extension point settings."""

    enabled: bool = False
    servers: list[dict[str, Any]] = Field(default_factory=list)


class CrewAIDeploymentSettings(BaseModel):
    """Default deployment settings for generated chatbots."""

    auth_mode: str = "private"
    static_bundle: bool = True
    docker_enabled: bool = True
    helm_enabled: bool = True


class CrewAIConfig(BaseModel):
    """File-backed CrewAI runtime configuration."""

    runtime: str = "crewai"
    process: str = "sequential"
    memory: CrewAIMemorySettings = Field(default_factory=CrewAIMemorySettings)
    knowledge: CrewAIKnowledgeSettings = Field(default_factory=CrewAIKnowledgeSettings)
    tracing: CrewAITracingSettings = Field(default_factory=CrewAITracingSettings)
    mcp: CrewAIMcpSettings = Field(default_factory=CrewAIMcpSettings)
    guardrails: CrewAIGuardrailSettings = Field(default_factory=CrewAIGuardrailSettings)
    deployment: CrewAIDeploymentSettings = Field(default_factory=CrewAIDeploymentSettings)
    output_schema: dict[str, Any] | str | None = "text"
    updated_at: datetime = Field(default_factory=datetime.utcnow)


def _config_path() -> Path:
    settings = get_settings()
    return Path(settings.app.crewai_storage_dir) / "runtime_config.json"


def _default_config() -> CrewAIConfig:
    settings = get_settings()
    return CrewAIConfig(
        process=settings.app.crewai_process_default,
        memory=CrewAIMemorySettings(
            enabled=settings.app.crewai_memory_enabled,
            storage_dir=settings.app.crewai_storage_dir,
        ),
    )


def _load_config() -> CrewAIConfig:
    path = _config_path()
    if not path.exists():
        return _default_config()
    try:
        return CrewAIConfig.model_validate(json.loads(path.read_text()))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load CrewAI config: {exc}",
        ) from exc


def _save_config(config: CrewAIConfig) -> CrewAIConfig:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    config.updated_at = datetime.utcnow()
    path.write_text(json.dumps(config.model_dump(mode="json"), indent=2))
    return config


@router.get("/config", response_model=CrewAIConfig)
async def get_crewai_config() -> CrewAIConfig:
    """Return persisted CrewAI runtime configuration."""
    return _load_config()


@router.put("/config", response_model=CrewAIConfig)
async def update_crewai_config(body: CrewAIConfig) -> CrewAIConfig:
    """Persist CrewAI runtime configuration."""
    if body.runtime != "crewai":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Delaxis is CrewAI-only; runtime must be 'crewai'.",
        )
    return _save_config(body)


@router.get("/capabilities")
async def get_crewai_capabilities() -> dict[str, Any]:
    """Return feature capability metadata for the command center."""
    config = _load_config()
    return {
        "runtime": "crewai",
        "process_modes": ["sequential", "hierarchical"],
        "features": {
            "crews": True,
            "flows": True,
            "memory": config.memory.enabled,
            "knowledge": config.knowledge.enabled,
            "tracing": config.tracing.enabled,
            "event_listeners": config.tracing.event_listeners,
            "mcp": config.mcp.enabled,
            "guardrails": config.guardrails.enabled,
            "deployment_auth_modes": ["public", "private", "keycloak"],
        },
        "config": config.model_dump(mode="json"),
    }
