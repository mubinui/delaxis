"""Unit tests for the builder's frontend generation contract and provider credentials."""

import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.api.routers import builder as builder_router
from src.api.routers.builder import (
    FrontendGenerateRequest,
    _ensure_frontend_contract,
    _get_provider_credentials,
    _render_themed_frontend,
)
from src.api.chatbot_page import page_defects
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


class TestThemedFrontend:
    """The themed path renders the shipped page, so its chat always works."""

    def _body(self, **overrides):
        params = dict(prompt="A support bot", workflow_id="wf", title="Support", greeting="Hi there")
        params.update(overrides)
        return FrontendGenerateRequest(**params)

    def test_renders_a_working_page_with_no_design_at_all(self):
        html, design = _render_themed_frontend(self._body(), {})
        assert page_defects(html) == []
        assert "wf" in html
        assert design["theme"] == "midnight"

    def test_design_controls_theme_copy_and_suggestions(self):
        html, design = _render_themed_frontend(
            self._body(),
            {
                "theme": "ocean",
                "title": "Helpdesk",
                "greeting": "Ask me anything",
                "suggestions": ["Reset my password", "  ", "Track an order"],
            },
        )
        assert design["theme"] == "ocean"
        assert design["title"] == "Helpdesk"
        assert design["suggestions"] == ["Reset my password", "Track an order"]
        assert "Ask me anything" in html
        assert page_defects(html) == []

    def test_brand_colours_are_applied_as_css_variables(self):
        html, design = _render_themed_frontend(
            self._body(), {"brand": {"accent": "#ff0066", "radius": "20px"}}
        )
        assert design["brand"]["accent"] == "#ff0066"
        assert design["brand"]["radius"] == "20px"
        assert "--accent: #ff0066;" in html
        assert "--brand-radius: 20px;" in html
        # The theme's white button text does not clear 4.5:1 on this pink, so
        # the guard supplies one that does rather than leaving it unreadable.
        assert design["brand"]["accent-text"] == "#111111"

    def test_a_design_cannot_inject_css_or_markup(self):
        html, design = _render_themed_frontend(
            self._body(),
            {"brand": {"accent": "red; } body { display:none", "bg": "</style><script>alert(1)</script>"}},
        )
        # Both values are dropped rather than written into the stylesheet
        assert design["brand"] == {}
        assert "red; }" not in html
        assert "alert(1)" not in html

    def test_greeting_cannot_break_out_of_the_script_block(self):
        html, _ = _render_themed_frontend(
            self._body(greeting="</script><script>alert(1)</script>"), {}
        )
        assert "alert(1)</script>" not in html


class TestGenerateEndpointFallback:
    def test_missing_key_returns_a_working_themed_page(self, providers_file, monkeypatch):
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
        assert body["mode"] == "themed"
        # Not a placeholder page: it is the real one, and it works
        assert page_defects(body["html"]) == []

    def test_unknown_provider_returns_400(self):
        app = FastAPI()
        app.include_router(builder_router.router)
        client = TestClient(app)
        response = client.post(
            "/api/v1/builder/frontend/generate",
            json={"prompt": "bot", "workflow_id": "wf", "provider_id": "ghost"},
        )
        assert response.status_code == 400


class TestHtmlExtraction:
    """A truncated response leaves an unterminated ```html fence; fence-pair
    matching alone let that marker leak into the deployed page."""

    def test_unterminated_fence_from_truncated_output(self):
        from src.api.routers.builder import _extract_html_from_text

        html = _extract_html_from_text(
            '```html\n<!doctype html>\n<html><head><title>Bot</title></head><body><div id="app">'
        )
        assert html is not None
        assert "```" not in html
        assert html.startswith("<!doctype html>")

    def test_uppercase_language_tag_is_not_left_in_the_page(self):
        from src.api.routers.builder import _extract_html_from_text

        html = _extract_html_from_text("```HTML\n<!doctype html><html><body>hi</body></html>\n```")
        assert html == "<!doctype html><html><body>hi</body></html>"

    def test_last_fenced_html_block_wins_over_earlier_blocks(self):
        from src.api.routers.builder import _extract_html_from_text

        html = _extract_html_from_text(
            '```json\n{"a":1}\n```\nand here it is:\n'
            "```html\n<!doctype html><html><body>x</body></html>\n```"
        )
        assert html == "<!doctype html><html><body>x</body></html>"

    def test_bare_document_without_a_fence(self):
        from src.api.routers.builder import _extract_html_from_text

        html = _extract_html_from_text("<!doctype html><html><body>hi</body></html>")
        assert html == "<!doctype html><html><body>hi</body></html>"

    def test_non_html_returns_none(self):
        from src.api.routers.builder import _extract_html_from_text

        assert _extract_html_from_text('```json\n{"a":1}\n```') is None


class TestCustomGenerationSafety:
    """Custom generation is where dead buttons came from, so anything that would
    not work as a chatbot is replaced by the page that does."""

    @pytest.fixture
    def client(self, providers_file, monkeypatch):
        providers_file([
            {
                "id": "p1",
                "type": "llm",
                "base_url": "https://x.example/v1",
                "auth": {"scheme": "bearer", "env_var": "P1_KEY", "required": True},
            }
        ])
        monkeypatch.setenv("P1_KEY", "sk-test")
        app = FastAPI()
        app.include_router(builder_router.router)
        return TestClient(app)

    def _generate(self, client, monkeypatch, raw: str, truncated: bool = False):
        async def _reply(*args, **kwargs):
            return raw, truncated

        monkeypatch.setattr(builder_router, "_call_llm_sync", _reply)
        response = client.post(
            "/api/v1/builder/frontend/generate",
            json={"prompt": "bot", "workflow_id": "wf", "provider_id": "p1", "mode": "custom"},
        )
        assert response.status_code == 200
        return response.json()

    def test_truncated_output_falls_back_to_the_working_page(self, client, monkeypatch):
        body = self._generate(client, monkeypatch, "```html\n<!doctype html><html><body>half", truncated=True)
        assert body["used_fallback"] is True
        assert body["mode"] == "themed"
        assert page_defects(body["html"]) == []

    def test_a_page_with_no_send_handler_is_rejected(self, client, monkeypatch):
        pretty_but_dead = (
            "<!doctype html><html><head><title>Bot</title></head><body>"
            "<script>const cfg = window.CHATBOT_CONFIG;</script>"
            "<input id='q' /><button>Send</button></body></html>"
        )
        body = self._generate(client, monkeypatch, pretty_but_dead)
        assert body["used_fallback"] is True
        assert "would not work" in body["summary"]

    def test_a_page_that_never_calls_the_api_is_rejected(self, client, monkeypatch):
        no_api = (
            "<!doctype html><html><head></head><body>"
            "<script>const cfg = window.CHATBOT_CONFIG;"
            "document.addEventListener('submit', () => {});</script>"
            "<textarea></textarea></body></html>"
        )
        body = self._generate(client, monkeypatch, no_api)
        assert body["used_fallback"] is True

    def test_a_complete_page_is_kept(self, client, monkeypatch):
        working = (
            "<!doctype html><html><head><title>Bot</title></head><body>"
            "<textarea id='q'></textarea><button id='s'>Send</button>"
            "<script>const cfg = window.CHATBOT_CONFIG;"
            "document.getElementById('s').addEventListener('click', async () => {"
            "  const r = await fetch(cfg.api_url + '/api/v1/sessions', {method:'POST'});"
            "  const s = await r.json();"
            "  await fetch(cfg.api_url + '/api/v1/sessions/' + s.session_id + '/messages', {method:'POST'});"
            "});</script></body></html>"
        )
        body = self._generate(client, monkeypatch, working)
        assert body["used_fallback"] is False
        assert body["mode"] == "custom"

    def test_a_cdn_dependency_is_rejected(self, client, monkeypatch):
        cdn_page = (
            "<!doctype html><html><head>"
            "<script src=\"https://cdn.jsdelivr.net/npm/marked/marked.min.js\"></script>"
            "</head><body><textarea></textarea>"
            "<script>const cfg = window.CHATBOT_CONFIG;"
            "document.addEventListener('submit', () => fetch(cfg.api_url + '/api/v1/sessions/x/messages'));"
            "</script></body></html>"
        )
        body = self._generate(client, monkeypatch, cdn_page)
        assert body["used_fallback"] is True
