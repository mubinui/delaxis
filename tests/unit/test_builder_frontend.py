"""Unit tests for the builder's frontend generation contract and provider credentials."""

import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.api.routers import builder as builder_router
from src.api.routers.builder import (
    FrontendGenerateRequest,
    _ensure_frontend_contract,
    _fallback_frontend,
    _get_provider_credentials,
)
from src.config import provider_registry


@pytest.fixture
def providers_file(tmp_path, monkeypatch):
    def _write(providers):
        path = tmp_path / "api_providers.json"
        path.write_text(json.dumps({"version": "2.0", "providers": providers}), encoding="utf-8")
        monkeypatch.setattr(provider_registry, "_providers_path", lambda: path)
        return path

    return _write


class TestFrontendContract:
    def test_config_injected_into_head_not_end_of_body(self):
        html = (
            "<html><head></head><body>"
            "<script>const cfg = window.CHATBOT_CONFIG; run(cfg);</script>"
            "</body></html>"
        )
        result = _ensure_frontend_contract(html)
        assert result.index("__CHATBOT_CONFIG__") < result.index("const cfg")

    def test_no_duplicate_markdown_css_with_multiple_styles(self):
        html = "<html><head><style>a{}</style><style>b{}</style></head><body></body></html>"
        result = _ensure_frontend_contract(html)
        assert result.count(".md-content p {") == 1

    def test_markdown_added_when_missing_style_block(self):
        html = "<html><head></head><body><script>x()</script></body></html>"
        result = _ensure_frontend_contract(html)
        assert ".md-content p {" in result
        assert "function renderMarkdown" in result


class TestProviderCredentials:
    def test_unknown_provider_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _get_provider_credentials("does-not-exist")
        assert exc_info.value.status_code == 400

    def test_keyless_local_provider_is_ready(self, providers_file):
        providers_file([
            {"id": "lm-studio", "type": "llm", "base_url": "http://localhost:1234/v1"},
        ])
        base_url, api_key, ready = _get_provider_credentials("lm-studio")
        assert base_url == "http://localhost:1234/v1"
        assert api_key == ""
        assert ready is True

    def test_key_required_but_missing_is_not_ready(self, providers_file, monkeypatch):
        providers_file([
            {
                "id": "p1",
                "type": "llm",
                "base_url": "https://x.example/v1",
                "auth": {"scheme": "bearer", "env_var": "P1_KEY", "required": True},
            }
        ])
        monkeypatch.delenv("P1_KEY", raising=False)
        _, _, ready = _get_provider_credentials("p1")
        assert ready is False

    def test_provider_without_endpoint_raises_400(self, providers_file):
        providers_file([{"id": "p1", "type": "llm"}])
        with pytest.raises(HTTPException) as exc_info:
            _get_provider_credentials("p1")
        assert exc_info.value.status_code == 400
        assert "base_url" in exc_info.value.detail


class TestFallbackFrontend:
    def _body(self, **overrides):
        params = dict(prompt="A support bot", workflow_id="wf", title="Support", greeting="Hi there")
        params.update(overrides)
        return FrontendGenerateRequest(**params)

    def test_config_placeholder_in_head(self):
        html = _fallback_frontend(self._body())
        assert html.index("__CHATBOT_CONFIG__") < html.index("<body>")

    def test_greeting_with_apostrophe_and_newline_stays_valid_js(self):
        html = _fallback_frontend(self._body(greeting="I'm here\nto help"))
        assert "add('assistant', cfg.greeting || \"I'm here\\nto help\");" in html
        assert "&#x27;" not in html

    def test_greeting_cannot_break_out_of_script(self):
        html = _fallback_frontend(self._body(greeting="</script><script>alert(1)</script>"))
        assert "alert(1)</script>" not in html


class TestGenerateEndpointFallback:
    def test_missing_key_returns_fallback_frontend(self, providers_file, monkeypatch):
        providers_file([
            {
                "id": "p1",
                "type": "llm",
                "base_url": "https://x.example/v1",
                "auth": {"scheme": "bearer", "env_var": "P1_KEY", "required": True},
            }
        ])
        monkeypatch.delenv("P1_KEY", raising=False)
        app = FastAPI()
        app.include_router(builder_router.router)
        client = TestClient(app)
        response = client.post(
            "/api/v1/builder/frontend/generate",
            json={"prompt": "bot", "workflow_id": "wf", "provider_id": "p1"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["used_fallback"] is True
        assert "__CHATBOT_CONFIG__" in body["html"]

    def test_unknown_provider_returns_400(self):
        app = FastAPI()
        app.include_router(builder_router.router)
        client = TestClient(app)
        response = client.post(
            "/api/v1/builder/frontend/generate",
            json={"prompt": "bot", "workflow_id": "wf", "provider_id": "ghost"},
        )
        assert response.status_code == 400
