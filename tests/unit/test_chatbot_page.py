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
        # A page has to actually be a chatbot: config, an input, a handler, and
        # calls to both session endpoints. Structure alone is not enough.
        html = (
            "<!doctype html><html><head><script>window.CHATBOT_CONFIG = {};"
            "function renderMarkdown(x){}</script></head><body>"
            "<textarea id='q'></textarea><button id='s'>Send</button>"
            "<script>document.getElementById('s').addEventListener('click', async () => {"
            "  const r = await fetch('/api/v1/sessions', {method:'POST'});"
            "  await fetch('/api/v1/sessions/' + (await r.json()).session_id + '/messages', {method:'POST'});"
            "});</script></body></html>"
        )
        assert validate_page(html) == []

    def test_a_page_that_looks_right_but_does_nothing_is_flagged(self):
        """Structurally valid, no way to send a message — what generation produced."""
        html = (
            "<!doctype html><html><head><script>window.CHATBOT_CONFIG = {};"
            "function renderMarkdown(x){}</script></head><body></body></html>"
        )
        warnings = validate_page(html)
        assert any("no conversation is ever created" in w.lower() or "/api/v1/sessions" in w for w in warnings)
        assert any("no text input" in w.lower() for w in warnings)


class TestContrastGuard:
    """A generated palette that looks fine in the abstract regularly fails in
    practice, so contrast is measured rather than trusted."""

    def test_contrast_ratio_matches_wcag_reference_values(self):
        from src.api.chatbot_page import contrast_ratio

        assert round(contrast_ratio("#000000", "#ffffff"), 1) == 21.0
        assert round(contrast_ratio("#ffffff", "#ffffff"), 1) == 1.0
        assert contrast_ratio("not-a-colour", "#fff") == 0.0

    def test_shorthand_hex_and_rgb_are_understood(self):
        from src.api.chatbot_page import contrast_ratio

        assert round(contrast_ratio("#000", "#fff"), 1) == 21.0
        assert round(contrast_ratio("rgb(0, 0, 0)", "rgb(255,255,255)"), 1) == 21.0

    def test_unreadable_body_text_is_corrected_and_the_background_kept(self):
        from src.api.chatbot_page import contrast_ratio, harmonize_brand

        # Pale grey text on a near-white background: legal CSS, unreadable page
        brand, notes = harmonize_brand("daylight", {"text": "#d8d4cc", "bg": "#f9f6f1"})
        assert brand["bg"] == "#f9f6f1", "the background carries the design's intent"
        assert brand["text"] != "#d8d4cc"
        assert contrast_ratio(brand["text"], brand["bg"]) >= 4.5
        assert notes

    def test_a_readable_palette_survives_untouched(self):
        from src.api.chatbot_page import harmonize_brand

        brand, notes = harmonize_brand(
            "daylight", {"text": "#1a1a1a", "bg": "#fffdf8", "accent": "#8a3b12", "accent-text": "#ffffff"}
        )
        assert brand["text"] == "#1a1a1a"
        assert brand["accent"] == "#8a3b12"
        assert notes == []

    def test_button_text_that_vanishes_on_its_own_accent_is_corrected(self):
        from src.api.chatbot_page import contrast_ratio, harmonize_brand

        brand, notes = harmonize_brand("midnight", {"accent": "#ffe08a", "accent-text": "#fff6d5"})
        assert brand["accent"] == "#ffe08a"
        assert contrast_ratio(brand["accent-text"], brand["accent"]) >= 4.5
        assert any("accent-text" in note for note in notes)

    def test_a_light_background_on_a_dark_theme_gets_dark_text(self):
        """The theme's own text colour is unusable here, so black/white is picked."""
        from src.api.chatbot_page import contrast_ratio, harmonize_brand

        brand, _ = harmonize_brand("midnight", {"bg": "#fafafa"})
        assert brand["bg"] == "#fafafa"
        assert contrast_ratio(brand["text"], "#fafafa") >= 4.5

    def test_panels_follow_a_new_page_background(self):
        """A cream page must not keep the theme's midnight panels bolted on."""
        from src.api.chatbot_page import _relative_luminance, _parse_color, harmonize_brand

        brand, _ = harmonize_brand("midnight", {"bg": "#f9f6f1"})
        for name in ("surface", "panel", "assistant-bubble", "input-bg"):
            luminance = _relative_luminance(_parse_color(brand[name]))
            assert luminance > 0.5, f"{name} stayed dark on a light background"

    def test_explicit_surfaces_are_not_overwritten(self):
        from src.api.chatbot_page import harmonize_brand

        brand, _ = harmonize_brand("midnight", {"bg": "#f9f6f1", "surface": "#ffffff"})
        assert brand["surface"] == "#ffffff"

    def test_every_pair_is_readable_after_harmonizing_a_hostile_palette(self):
        from src.api.chatbot_page import CONTRAST_PAIRS, THEMES, contrast_ratio, harmonize_brand

        hostile = {"bg": "#f9f6f1", "text": "#f2efe8", "muted": "#f0ece4", "accent": "#efe9dd", "accent-text": "#f5f2ec"}
        brand, notes = harmonize_brand("sunset", hostile)
        assert notes
        merged = {**THEMES["sunset"], **brand}
        for foreground, background, minimum in CONTRAST_PAIRS:
            assert contrast_ratio(merged[foreground], merged[background]) >= minimum, f"{foreground} on {background}"


class TestErrorText:
    """The failure message a visitor actually reads.

    The API reports errors as a structured object. Handing that object to
    ``Error()`` renders "[object Object]" — which is what the page did, for
    every backend failure, hiding the one line that would have explained it.
    These run the real function out of the real page against the shapes the
    backend actually returns.
    """

    @staticmethod
    def _run(raw: str, status: int) -> str:
        import json as _json
        import shutil
        import subprocess

        import pytest

        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not available to execute the page's JavaScript")

        page = default_chatbot_html(
            title="Bot", greeting="Hi", workflow_id="wf_1",
            provider_id="openrouter", model_id="", theme="midnight",
            config={"workflow_id": "wf_1"},
        )
        start = page.index("function errorText(raw, status) {")
        end = page.index("async function api(path, options) {", start)
        script = page[start:end] + (
            f"\nprocess.stdout.write(errorText({_json.dumps(raw)}, {status}));"
        )
        result = subprocess.run(
            [node, "--input-type=module", "-e", script],
            capture_output=True, text=True, check=True,
        )
        return result.stdout

    def test_structured_detail_yields_the_readable_line(self):
        body = json.dumps({"detail": {
            "error_code": "MESSAGE_PROCESSING_FAILED",
            "error_message": "Failed to send message: Connection refused.",
            "error_type": "ConnectionError",
        }})
        assert self._run(body, 500) == "Failed to send message: Connection refused."

    def test_never_renders_object_object(self):
        body = json.dumps({"detail": {"error_code": "X", "error_message": "boom"}})
        assert "[object Object]" not in self._run(body, 500)

    def test_string_detail_passes_through(self):
        assert self._run(json.dumps({"detail": "Not Found"}), 404) == "Not Found"

    def test_validation_list_is_joined(self):
        body = json.dumps({"detail": [
            {"loc": ["body", "query"], "msg": "Field required"},
            {"loc": ["body", "sessionId"], "msg": "Field required"},
        ]})
        assert self._run(body, 422) == "Field required; Field required"

    def test_top_level_error_message_without_detail(self):
        assert self._run(json.dumps({"error_message": "Rate limited"}), 429) == "Rate limited"

    def test_plain_text_body_survives(self):
        assert self._run("upstream timeout", 504) == "upstream timeout"

    def test_empty_body_falls_back_to_the_status(self):
        assert self._run("", 502) == "Request failed with 502"


class TestAttachments:
    """File upload in the deployed chat page.

    The page is generated as one HTML string, so these assert the machinery is
    present and wired rather than driving a browser; the end-to-end behaviour is
    covered by exercising the RAG upload endpoint it posts to.
    """

    @staticmethod
    def _page() -> str:
        return default_chatbot_html(
            title="Bot", greeting="Hi", workflow_id="wf_1",
            provider_id="openrouter", model_id="", theme="midnight",
            config={"workflow_id": "wf_1"},
        )

    def test_the_composer_has_an_attach_control(self):
        page = self._page()
        assert 'id="attach"' in page and 'id="files"' in page and 'id="chips"' in page

    def test_uploads_go_to_a_per_conversation_collection(self):
        # One visitor's uploads must not be retrievable from another's chat.
        page = self._page()
        assert "'chat-' + sessionId" in page
        assert "/api/v1/rag/collections/" in page

    def test_multipart_upload_does_not_set_its_own_content_type(self):
        # Setting it by hand omits the boundary the browser generates, and the
        # server rejects the body as malformed.
        page = self._page()
        upload = page[page.index("async function uploadStaged"):]
        upload = upload[:upload.index("\n    }")]
        assert "FormData" in upload
        assert "Content-Type" not in upload

    def test_the_passages_travel_with_the_question(self):
        # Naming the file and telling the agent to retrieve it only works if that
        # workflow happens to have a retrieval tool. Asked about a file it could
        # not read, a model answers from the filename and invents the contents.
        page = self._page()
        assert "withAttachmentContext" in page
        helper = page[page.index("async function withAttachmentContext"):]
        helper = helper[:helper.index("\n    async function send")]
        assert "top_k" in helper
        assert "The relevant extracts follow" in helper
        assert "could not be read" in helper      # the honest path when retrieval fails

    def test_attachments_are_shown_in_the_sent_message(self):
        assert "message.attachments" in self._page()

    def test_drag_and_drop_is_accepted(self):
        assert "dragover" in self._page() and "drop" in self._page()


class TestPageGeneration:
    """Deployed pages are written to disk, so they need a way to be refreshed."""

    @staticmethod
    def _page() -> str:
        return default_chatbot_html(
            title="Bot", greeting="Hi", workflow_id="wf_1", provider_id="openrouter",
            model_id="", theme="midnight", config={"workflow_id": "wf_1"},
        )

    def test_generated_pages_are_stamped(self):
        from src.api.chatbot_page import PAGE_VERSION, page_generation

        assert page_generation(self._page()) == PAGE_VERSION

    def test_a_custom_page_is_not_claimed(self):
        from src.api.chatbot_page import page_generation

        # Returning a number here would mean overwriting somebody else's HTML.
        assert page_generation("<html><body>my own page</body></html>") is None

    def test_pages_predating_the_stamp_are_still_recognised(self):
        from src.api.chatbot_page import page_generation

        legacy = '<html><body><div id="chats"></div><div class="composer"></div></body></html>'
        assert page_generation(legacy) == 1

    def test_an_untemplated_page_is_not_mistaken_for_generated(self):
        from src.api.chatbot_page import page_generation

        # A raw template still holding its placeholder has not been rendered.
        assert page_generation('<div id="chats"></div><div class="composer">__CHATBOT_CONFIG__</div>') is None
