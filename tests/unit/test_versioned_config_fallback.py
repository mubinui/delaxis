"""Regression tests for degraded versioned-config behavior."""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import CurrentUser, UserRole, get_current_user, require_user
from src.api.routers import api_providers, configs, prompts


class _UnavailableVersionedService:
    def __init__(self, *args, **kwargs):
        pass

    def is_available(self) -> bool:
        return False


@pytest.fixture
def current_user() -> CurrentUser:
    return CurrentUser(role=UserRole.ADMIN, auth_method="development", username="tester")


def test_list_prompts_falls_back_when_versioning_schema_missing(
    tmp_path, monkeypatch, current_user
):
    config_path = tmp_path / "prompt_templates.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "contexts": [
                    {
                        "id": "default_system",
                        "name": "Default System",
                        "description": "Default prompt",
                        "prompt": "You are helpful.",
                        "variables": [],
                        "category": "system",
                    }
                ],
                "fallbacks": {},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/orchestration")
    monkeypatch.setattr(prompts, "VERSIONED_SERVICE_AVAILABLE", True)
    monkeypatch.setattr(prompts, "VersionedConfigService", _UnavailableVersionedService)
    monkeypatch.setattr(prompts, "_get_prompts_config_path", lambda: Path(config_path))

    app = FastAPI()
    app.include_router(prompts.router)
    app.dependency_overrides[get_current_user] = lambda: current_user

    with TestClient(app) as client:
        response = client.get("/api/v1/prompts")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == "default_system"
    assert body[0]["version"] is None
    assert body[0]["etag"] is None


def test_list_api_providers_falls_back_when_versioning_schema_missing(
    tmp_path, monkeypatch, current_user
):
    config_path = tmp_path / "api_providers.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "providers": [
                    {
                        "id": "openrouter",
                        "name": "OpenRouter",
                        "type": "llm",
                        "description": "Primary provider",
                        "base_url": "https://openrouter.ai/api/v1",
                        "enabled": True,
                        "config": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/orchestration")
    monkeypatch.setattr(api_providers, "VERSIONED_SERVICE_AVAILABLE", True)
    monkeypatch.setattr(api_providers, "VersionedConfigService", _UnavailableVersionedService)
    monkeypatch.setattr(api_providers, "_get_api_providers_config_path", lambda: Path(config_path))

    app = FastAPI()
    app.include_router(api_providers.router)
    app.dependency_overrides[get_current_user] = lambda: current_user

    with TestClient(app) as client:
        response = client.get("/api/v1/api-providers")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == "openrouter"
    assert body[0]["version"] is None
    assert body[0]["etag"] is None


def test_configs_dependency_returns_503_when_versioning_schema_missing(monkeypatch, current_user):
    class _FakeSettings:
        database_url = "postgresql://example.test/orchestration"

    monkeypatch.setattr(configs, "VERSIONED_SERVICE_AVAILABLE", True)
    monkeypatch.setattr(configs, "VersionedConfigService", _UnavailableVersionedService)
    monkeypatch.setattr(configs, "get_settings", lambda: _FakeSettings())

    app = FastAPI()
    app.include_router(configs.router)
    app.dependency_overrides[require_user] = lambda: current_user

    with TestClient(app) as client:
        response = client.get("/api/v1/configs/prompt/default_system")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Configuration versioning backend is not initialized. Apply database migrations to enable version history."
    )
