"""Unit tests for the shared chatbot page generator (themes, injection, escaping)."""

import json

from src.api.chatbot_page import (
    DEFAULT_THEME,
    THEMES,
    default_chatbot_html,
    ensure_config_contract,
    ensure_markdown_support,
    inject_runtime_config,
    normalize_theme,
    safe_json,
    theme_css,
    theme_presets,
    validate_page,
)


class TestSafeJson:
    def test_escapes_script_close(self):
        payload = {"greeting": "</script><script>alert(1)</script>"}
        encoded = safe_json(payload)
        assert "</script>" not in encoded
        assert json.loads(encoded.replace("<\\/", "</")) == payload

    def test_round_trips_plain_data(self):
        payload = {"workflow_id": "demo", "n": 3}
        assert json.loads(safe_json(payload)) == payload


class TestConfigContract:
    def test_injects_into_head(self):
        html = "<html><head><title>x</title></head><body><script>app()</script></body></html>"
        result = ensure_config_contract(html)
        assert "__CHATBOT_CONFIG__" in result
        assert result.index("__CHATBOT_CONFIG__") < result.index("<title>")

    def test_config_lands_before_first_app_script(self):
        html = "<html><head></head><body><script>const cfg = window.CHATBOT_CONFIG;</script></body></html>"
        result = inject_runtime_config(html, {"workflow_id": "wf"})
        assert result.index("window.CHATBOT_CONFIG = {") < result.index("const cfg")

    def test_no_head_falls_back_to_before_first_script(self):
        html = "<div>hi</div><script>use(window.CHATBOT_CONFIG)</script>"
        result = ensure_config_contract(html)
        assert result.index("__CHATBOT_CONFIG__") < result.index("<script>use")

    def test_no_anchors_prepends(self):
        html = "<div>static page</div>"
        result = ensure_config_contract(html)
        assert result.startswith("<script>window.CHATBOT_CONFIG")

    def test_existing_placeholder_untouched(self):
        html = "<head><script>window.CHATBOT_CONFIG = __CHATBOT_CONFIG__;</script></head>"
        assert ensure_config_contract(html) == html

    def test_substitution_is_script_safe(self):
        html = "<head></head><body></body>"
        result = inject_runtime_config(html, {"greeting": "bye</script><script>alert(1)"})
        assert "alert(1)</script>" not in result
        assert "__CHATBOT_CONFIG__" not in result


class TestMarkdownSupport:
    def test_noop_when_renderer_present(self):
        html = "<html><script>function renderMarkdown(x){}</script></html>"
        assert ensure_markdown_support(html) == html

    def test_injects_style_and_script_once(self):
        html = "<html><head><style>body{}</style></head><body></body></html>"
        result = ensure_markdown_support(html)
        assert result.count(".md-content p {") == 1
        assert result.count("function renderMarkdown") == 1

    def test_multiple_style_blocks_get_single_injection(self):
        html = "<html><head><style>a{}</style><style>b{}</style></head><body></body></html>"
        result = ensure_markdown_support(html)
        assert result.count(".md-content p {") == 1

    def test_script_lands_in_head_before_body_scripts(self):
        html = "<html><head></head><body><script>renderMarkdown('x')</script></body></html>"
        result = ensure_markdown_support(html)
        assert result.index("function renderMarkdown") < result.index("renderMarkdown('x')")

    def test_page_without_style_still_gets_css(self):
        html = "<html><head></head><body></body></html>"
        result = ensure_markdown_support(html)
        assert ".md-content p {" in result

    def test_page_without_any_anchor_still_gets_both(self):
        html = "<div>bare</div>"
        result = ensure_markdown_support(html)
        assert ".md-content p {" in result
        assert "function renderMarkdown" in result


class TestThemes:
    def test_all_presets_have_the_same_variables(self):
        expected = set(THEMES[DEFAULT_THEME])
        for theme_id, variables in THEMES.items():
            assert set(variables) == expected, theme_id

    def test_theme_css_emits_root_block(self):
        css = theme_css("ocean")
        assert css.startswith(":root {")
        assert f"--bg: {THEMES['ocean']['bg']};" in css

    def test_unknown_theme_falls_back_to_default(self):
        assert normalize_theme("neon-zebra") == DEFAULT_THEME
        assert theme_css("neon-zebra") == theme_css(DEFAULT_THEME)

    def test_presets_listing_shape(self):
        presets = theme_presets()
        assert {p["id"] for p in presets} == set(THEMES)
        assert all(p["label"] and p["vars"] for p in presets)


class TestDefaultChatbotHtml:
    def _render(self, **overrides):
        params = dict(
            title="My Bot",
            greeting="Hello!",
            workflow_id="wf_1",
            provider_id="openrouter",
            model_id="openai/gpt-oss-20b",
            theme="midnight",
            config={"workflow_id": "wf_1", "greeting": "Hello!", "api_url": ""},
        )
        params.update(overrides)
        return default_chatbot_html(**params)

    def test_escapes_hostile_title(self):
        html = self._render(title='</title><script>alert(1)</script>')
        assert "<script>alert(1)</script>" not in html

    def test_theme_variables_present(self):
        for theme_id, variables in THEMES.items():
            html = self._render(theme=theme_id)
            assert f"--bg: {variables['bg']};" in html

    def test_config_in_head_before_app_script(self):
        html = self._render()
        assert html.index("window.CHATBOT_CONFIG =") < html.index("const cfg = window.CHATBOT_CONFIG")

    def test_validates_clean(self):
        assert validate_page(self._render()) == []


class TestValidatePage:
    def test_flags_bare_fragment(self):
        warnings = validate_page("<div>hello</div>")
        assert len(warnings) >= 4

    def test_clean_page_passes(self):
        html = (
            "<!doctype html><html><head><script>window.CHATBOT_CONFIG = {};"
            "function renderMarkdown(x){}</script></head><body></body></html>"
        )
        assert validate_page(html) == []
