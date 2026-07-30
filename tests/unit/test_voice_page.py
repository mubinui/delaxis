"""Injecting the voice client into a deployed page, and keeping it self-contained.

A deployed page is served from this application with no guaranteed network
egress and no provider credentials, so the voice client must be fully inlined and
must never reference a third-party origin. The page validator is what enforces
that, and these tests are what keep the validator honest.
"""

import json

import pytest

from src.api.chatbot_page import (
    default_chatbot_html,
    ensure_markdown_support,
    ensure_voice_support,
    page_defects,
    validate_page,
)

CONFIG = {
    "name": "support-bot",
    "workflow_id": "assistant_chat",
    "greeting": "Hi there",
    "api_url": "",
    "voice": {"enabled": True, "greeting_spoken": True},
}


def voice_page():
    html = default_chatbot_html(
        title="Support",
        greeting="Hi there",
        workflow_id="assistant_chat",
        provider_id="gemini",
        model_id="gemini-3.6-flash",
        theme="midnight",
        config=CONFIG,
        voice_enabled=True,
    )
    return ensure_voice_support(html)


def plain_page():
    return default_chatbot_html(
        title="Support",
        greeting="Hi there",
        workflow_id="assistant_chat",
        provider_id="gemini",
        model_id="gemini-3.6-flash",
        theme="midnight",
        config={"name": "support-bot"},
        voice_enabled=False,
    )


class TestVoiceInjection:
    def test_voice_page_has_no_defects(self):
        assert page_defects(voice_page()) == []

    def test_voice_page_has_no_warnings(self):
        assert validate_page(voice_page(), voice_enabled=True) == []

    def test_no_placeholders_survive(self):
        html = voice_page()
        assert "__VOICE_STYLE__" not in html
        assert "__CHATBOT_CONFIG__" not in html

    def test_is_idempotent(self):
        once = voice_page()
        assert ensure_voice_support(once) == once

    def test_composes_with_markdown_support(self):
        html = ensure_markdown_support(ensure_voice_support("<html><head></head><body></body></html>"))
        assert "function renderMarkdown" in html
        assert "const VOICE = (function" in html
        assert page_defects(html)  # a bare shell is still not a working chatbot

    def test_injects_into_a_page_with_no_style_or_head(self):
        html = ensure_voice_support("<div>hand written</div>")
        assert "const VOICE = (function" in html
        assert ".mic" in html

    def test_mic_button_present_and_hidden_by_default(self):
        # The template ships the button hidden; the voice client unhides it only
        # when the deployment enables voice, so a text-only page has no dead control.
        assert 'id="mic"' in plain_page()
        assert "hidden" in plain_page().split('id="mic"')[1][:80]

    def test_plain_page_carries_no_voice_client(self):
        assert "const VOICE = (function" not in plain_page()
        assert "/api/v1/voice/ticket" not in plain_page()


class TestSelfContained:
    def test_never_references_the_provider_origin(self):
        # The entire reason audio is relayed server-side.
        assert "googleapis.com" not in voice_page()
        assert "generativelanguage" not in voice_page()

    def test_no_external_asset_or_socket(self):
        assert not any("external" in d for d in page_defects(voice_page()))

    def test_uses_a_relative_socket(self):
        # Built from location.host rather than a literal absolute URL.
        assert "location.host" in voice_page()


class TestExternalWebSocketDefect:
    def test_flags_a_direct_provider_socket(self):
        html = plain_page().replace(
            "</body>",
            "<script>const s = new WebSocket('wss://generativelanguage.googleapis.com/ws');</script></body>",
        )
        assert any("WebSocket to an external host" in d for d in page_defects(html))

    def test_flags_any_third_party_socket(self):
        html = plain_page().replace(
            "</body>", "<script>new WebSocket(\"ws://evil.test/relay\")</script></body>"
        )
        assert any("WebSocket to an external host" in d for d in page_defects(html))

    def test_allows_localhost_for_development_pages(self):
        html = plain_page().replace(
            "</body>", "<script>new WebSocket('ws://localhost:8000/api/v1/voice/ws')</script></body>"
        )
        assert not any("WebSocket to an external host" in d for d in page_defects(html))

    def test_does_not_flag_the_injected_client(self):
        assert not any("WebSocket to an external host" in d for d in page_defects(voice_page()))


class TestVoiceWarning:
    def test_warns_when_voice_enabled_but_client_missing(self):
        # Catches a hand-edited page that dropped the voice script.
        warnings = validate_page(plain_page(), voice_enabled=True)
        assert any("no voice client" in w for w in warnings)

    def test_no_warning_when_voice_is_off(self):
        assert not any("voice" in w.lower() for w in validate_page(plain_page(), voice_enabled=False))


class TestConfigPrivacy:
    def test_only_public_voice_fields_reach_the_page(self):
        from src.api.routers.deployments import DeploymentVoiceConfig, _public_voice_config

        public = _public_voice_config(
            DeploymentVoiceConfig(
                enabled=True,
                model="gemini-3.1-flash-live-preview",
                voice_name="Kore",
                system_prompt="You are Ada, and the launch code is hunter2.",
            )
        )
        assert public == {"enabled": True, "greeting_spoken": True}
        # window.CHATBOT_CONFIG is readable and editable by every visitor.
        assert "system_prompt" not in public
        assert "model" not in public
        assert "voice_name" not in public

    def test_secrets_absent_from_the_rendered_page(self):
        html = voice_page()
        assert "hunter2" not in html
        assert "gemini-3.1-flash-live-preview" not in html
