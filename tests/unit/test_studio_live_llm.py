"""Unit tests for the studio's live LLM tester.

The endpoint used to call litellm, which this project does not depend on, so it
failed for every provider with "No module named 'litellm'". It now goes through
the provider registry's OpenAI-compatible endpoint over plain HTTP.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routers import studio as studio_router
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
                        "id": "gemini",
                        "name": "Google Gemini",
                        "type": "llm",
                        "description": "keyed provider",
                        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                        "litellm_prefix": "gemini",
                        "auth": {"scheme": "bearer", "env_var": "GEMINI_API_KEY", "required": True},
                    },
                    {
                        "id": "local-box",
                        "name": "Local Box",
                        "type": "llm",
                        "description": "keyless local provider",
                        "base_url": "http://localhost:1234/v1",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(provider_registry, "_providers_path", lambda: config_path)

    app = FastAPI()
    app.include_router(studio_router.router)
    return TestClient(app)


def _stub_post(monkeypatch, payload, status_code=200):
    class _Response:
        def __init__(self):
            self.status_code = status_code
            self.text = json.dumps(payload)

        def json(self):
            return payload

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            _Client.last = {"url": url, "headers": headers, "json": json}
            return _Response()

    monkeypatch.setattr(studio_router.httpx, "AsyncClient", _Client)
    return _Client


OK_PAYLOAD = {
    "choices": [{"message": {"content": "connected."}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
}


def test_call_hits_the_provider_endpoint_with_its_key(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "sk-gemini")
    stub = _stub_post(monkeypatch, OK_PAYLOAD)

    body = client.post(
        "/api/v1/studio/test-llm",
        json={"provider": "gemini", "model": "gemini-3.5-flash", "user_prompt": "hi"},
    ).json()

    assert body["response"] == "connected."
    assert body["token_usage"]["total_tokens"] == 13
    assert stub.last["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert stub.last["headers"]["Authorization"] == "Bearer sk-gemini"


def test_provider_prefix_is_stripped_from_the_model_id(client, monkeypatch):
    """Providers expect their own bare id; 'gemini/gemini-3.5-flash' would 404."""
    monkeypatch.setenv("GEMINI_API_KEY", "sk-gemini")
    stub = _stub_post(monkeypatch, OK_PAYLOAD)

    client.post(
        "/api/v1/studio/test-llm",
        json={"provider": "gemini", "model": "gemini/gemini-3.5-flash", "user_prompt": "hi"},
    )

    assert stub.last["json"]["model"] == "gemini-3.5-flash"


def test_request_api_key_overrides_the_configured_one(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "sk-from-env")
    stub = _stub_post(monkeypatch, OK_PAYLOAD)

    client.post(
        "/api/v1/studio/test-llm",
        json={"provider": "gemini", "model": "gemini-3.5-flash", "user_prompt": "hi", "api_key": "sk-pasted"},
    )

    assert stub.last["headers"]["Authorization"] == "Bearer sk-pasted"


def test_keyless_provider_is_called_without_auth(client, monkeypatch):
    stub = _stub_post(monkeypatch, OK_PAYLOAD)

    body = client.post(
        "/api/v1/studio/test-llm",
        json={"provider": "local-box", "model": "local-model", "user_prompt": "hi"},
    ).json()

    assert body["response"] == "connected."
    assert "Authorization" not in stub.last["headers"]


def test_missing_key_returns_400_not_a_module_error(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    response = client.post(
        "/api/v1/studio/test-llm",
        json={"provider": "gemini", "model": "gemini-3.5-flash", "user_prompt": "hi"},
    )

    assert response.status_code == 400
    assert "API key" in response.json()["detail"]


def test_unknown_provider_returns_400(client):
    response = client.post(
        "/api/v1/studio/test-llm",
        json={"provider": "ghost", "model": "m", "user_prompt": "hi"},
    )
    assert response.status_code == 400


def test_upstream_error_is_reported_as_502(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "sk-gemini")
    _stub_post(monkeypatch, {"error": {"message": "bad key"}}, status_code=401)

    response = client.post(
        "/api/v1/studio/test-llm",
        json={"provider": "gemini", "model": "gemini-3.5-flash", "user_prompt": "hi"},
    )

    assert response.status_code == 502
    assert "HTTP 401" in response.json()["detail"]["error"]


def test_endpoint_does_not_depend_on_litellm():
    """litellm is not a dependency; importing it here would break every call."""
    import inspect

    source = inspect.getsource(studio_router.test_live_llm)
    assert "import litellm" not in source
