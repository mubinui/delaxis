"""Unit tests for live provider model discovery.

Hardcoded model lists go stale as providers ship releases, so the studio reads
each provider's own /models endpoint and only falls back to the saved list.
"""

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routers import api_providers as api_providers_router
from src.config import provider_registry


@pytest.fixture
def client(tmp_path, monkeypatch):
    config_path = tmp_path / "api_providers.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "2.0",
                "providers": [
                    {
                        "id": "cloudy",
                        "name": "Cloudy",
                        "type": "llm",
                        "description": "keyed provider",
                        "base_url": "https://cloudy.example/v1",
                        "auth": {"scheme": "bearer", "env_var": "CLOUDY_KEY", "required": True},
                        "models": [{"name": "cloudy-pinned"}],
                    },
                    {
                        "id": "local-box",
                        "name": "Local Box",
                        "type": "llm",
                        "description": "keyless local provider",
                        "base_url": "http://localhost:1234/v1",
                        "models": [{"name": "saved-model"}],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(api_providers_router, "_get_api_providers_config_path", lambda: config_path)
    monkeypatch.setattr(provider_registry, "_providers_path", lambda: config_path)

    app = FastAPI()
    app.include_router(api_providers_router.router)
    return TestClient(app)


def _stub_models_response(monkeypatch, payload, status_code=200):
    class _Response:
        def __init__(self):
            self.status_code = status_code

        def raise_for_status(self):
            if status_code >= 400:
                raise httpx.HTTPStatusError("boom", request=None, response=None)

        def json(self):
            return payload

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            _Client.last_url = url
            _Client.last_headers = headers
            return _Response()

    monkeypatch.setattr(api_providers_router.httpx, "AsyncClient", _Client)
    return _Client


def test_live_models_are_discovered(client, monkeypatch):
    monkeypatch.setenv("CLOUDY_KEY", "sk-test")
    stub = _stub_models_response(monkeypatch, {"data": [{"id": "cloudy-v9"}, {"id": "cloudy-v8"}]})

    body = client.get("/api/v1/api-providers/cloudy/models").json()

    assert body["live"] is True
    assert body["source"] == "live"
    assert stub.last_url == "https://cloudy.example/v1/models"
    assert stub.last_headers["Authorization"] == "Bearer sk-test"
    names = [m["name"] for m in body["models"]]
    # Curated entries stay first, discovered models follow
    assert names[0] == "cloudy-pinned"
    assert {"cloudy-v9", "cloudy-v8"} <= set(names)


def test_configured_models_are_never_lost(client, monkeypatch):
    monkeypatch.setenv("CLOUDY_KEY", "sk-test")
    _stub_models_response(monkeypatch, {"data": [{"id": "brand-new"}]})

    body = client.get("/api/v1/api-providers/cloudy/models").json()

    assert "cloudy-pinned" in [m["name"] for m in body["models"]]


def test_missing_key_falls_back_to_saved_list(client, monkeypatch):
    monkeypatch.delenv("CLOUDY_KEY", raising=False)

    body = client.get("/api/v1/api-providers/cloudy/models").json()

    assert body["live"] is False
    assert "API key" in body["warning"]
    assert [m["name"] for m in body["models"]] == ["cloudy-pinned"]


def test_unreachable_endpoint_falls_back_to_saved_list(client, monkeypatch):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(api_providers_router.httpx, "AsyncClient", _Client)

    body = client.get("/api/v1/api-providers/local-box/models").json()

    assert body["live"] is False
    assert "Could not reach" in body["warning"]
    assert [m["name"] for m in body["models"]] == ["saved-model"]


def test_keyless_provider_is_queried_without_auth_header(client, monkeypatch):
    stub = _stub_models_response(monkeypatch, {"data": [{"id": "loaded-model"}]})

    body = client.get("/api/v1/api-providers/local-box/models").json()

    assert body["live"] is True
    assert "Authorization" not in stub.last_headers
    assert "loaded-model" in [m["name"] for m in body["models"]]


def test_live_false_skips_the_network(client, monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("network must not be touched when live=false")

    monkeypatch.setattr(api_providers_router.httpx, "AsyncClient", _boom)

    body = client.get("/api/v1/api-providers/cloudy/models?live=false").json()

    assert body["live"] is False
    assert [m["name"] for m in body["models"]] == ["cloudy-pinned"]


def test_unknown_provider_returns_404(client):
    assert client.get("/api/v1/api-providers/ghost/models").status_code == 404


def test_seeded_models_are_not_stale_placeholders():
    """Guard against the seed list drifting back to superseded generations."""
    from pathlib import Path

    config = json.loads(Path("configs/api_providers.json").read_text(encoding="utf-8"))
    names = {
        str(model.get("name", ""))
        for provider in config["providers"]
        for model in provider.get("models", [])
    }
    retired = {"gpt-4o", "gpt-4o-mini", "o3-mini", "gemini-2.5-flash", "gemini-2.5-pro"}
    assert not (names & retired), f"superseded models still seeded: {names & retired}"
