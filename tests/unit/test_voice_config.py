"""Resolving a realtime voice route from provider config.

The live model id is configuration rather than code because provider naming
churns; these tests pin the precedence order and, more importantly, that a model
which is not a realtime audio model is refused before any billable session can
be opened.
"""

import json

import pytest

from src.api.voice import config as voice_config
from src.api.voice.config import VoiceConfigError, load_live_config, voice_providers

LIVE_BLOCK = {
    "enabled": True,
    "protocol": "bidi_generate_content_v1beta",
    "ws_url": "wss://example.test/ws",
    "auth_query_param": "key",
    "model_env": "GEMINI_LIVE_MODEL",
    "model_prefix": "models/",
    "input": {"mime_type": "audio/pcm;rate=16000", "sample_rate": 16000},
    "output": {"sample_rate": 24000},
    "max_session_seconds": 300,
    "voices": ["Puck", "Kore"],
    "models": [
        {"name": "gemini-3.1-flash-live-preview", "default": True},
        {"name": "gemini-2.5-flash-native-audio-preview-12-2025"},
    ],
}


def _providers_file(tmp_path, live=LIVE_BLOCK, extra=None):
    provider = {
        "id": "gemini",
        "name": "Google Gemini",
        "type": "llm",
        "base_url": "https://example.test/v1",
        "litellm_prefix": "gemini",
        "enabled": True,
        "auth": {"scheme": "bearer", "env_var": "GEMINI_API_KEY", "required": True},
        "models": [{"name": "gemini-3.6-flash", "default": True}],
    }
    if live is not None:
        provider["live"] = live
    if extra:
        provider.update(extra)
    path = tmp_path / "api_providers.json"
    path.write_text(json.dumps({"version": "1.0", "providers": [provider]}))
    return path


@pytest.fixture
def providers(tmp_path, monkeypatch):
    path = _providers_file(tmp_path)
    monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)
    monkeypatch.delenv("GEMINI_LIVE_MODEL", raising=False)
    return path


class TestModelResolution:
    def test_falls_back_to_configured_default(self, providers):
        assert load_live_config("gemini").model == "gemini-3.1-flash-live-preview"

    def test_env_override_wins_over_default(self, providers, monkeypatch):
        monkeypatch.setenv("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
        assert load_live_config("gemini").model == "gemini-2.5-flash-native-audio-preview-12-2025"

    def test_explicit_request_wins_over_env(self, providers, monkeypatch):
        monkeypatch.setenv("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
        resolved = load_live_config("gemini", model="gemini-3.1-flash-live-preview")
        assert resolved.model == "gemini-3.1-flash-live-preview"

    def test_requested_model_must_be_allow_listed(self, providers):
        # The deployed page's config is visitor-editable, so an unchecked model
        # would let anyone point the bridge at an arbitrary billed model.
        with pytest.raises(VoiceConfigError, match="not in the live allow-list"):
            load_live_config("gemini", model="some-expensive-model")

    def test_env_override_must_be_allow_listed(self, providers, monkeypatch):
        monkeypatch.setenv("GEMINI_LIVE_MODEL", "typo-flash-live")
        with pytest.raises(VoiceConfigError, match="not in the live allow-list"):
            load_live_config("gemini")

    def test_upstream_model_carries_the_prefix(self, providers):
        assert load_live_config("gemini").upstream_model == "models/gemini-3.1-flash-live-preview"


class TestAudioCapabilityGate:
    def test_text_only_model_is_refused(self, tmp_path, monkeypatch):
        live = {**LIVE_BLOCK, "models": [{"name": "gemini-3.6-flash", "default": True}]}
        path = _providers_file(tmp_path, live=live)
        monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)
        monkeypatch.delenv("GEMINI_LIVE_MODEL", raising=False)
        # gemini-3.6-flash is the text model; it must not open an audio session.
        with pytest.raises(VoiceConfigError, match="realtime audio model"):
            load_live_config("gemini")

    @pytest.mark.parametrize(
        "model",
        [
            "gemini-3.1-flash-live-preview",
            "gemini-2.5-flash-native-audio-preview-12-2025",
            "gemini-live-2.5-flash-native-audio",
        ],
    )
    def test_realtime_names_are_accepted(self, tmp_path, monkeypatch, model):
        live = {**LIVE_BLOCK, "models": [{"name": model, "default": True}]}
        path = _providers_file(tmp_path, live=live)
        monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)
        monkeypatch.delenv("GEMINI_LIVE_MODEL", raising=False)
        assert load_live_config("gemini").model == model


class TestGuards:
    def test_missing_live_block_is_refused(self, tmp_path, monkeypatch):
        path = _providers_file(tmp_path, live=None)
        monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)
        with pytest.raises(VoiceConfigError, match="no live voice support"):
            load_live_config("gemini")

    def test_disabled_live_block_is_refused(self, tmp_path, monkeypatch):
        path = _providers_file(tmp_path, live={**LIVE_BLOCK, "enabled": False})
        monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)
        with pytest.raises(VoiceConfigError, match="disabled"):
            load_live_config("gemini")

    def test_unknown_protocol_is_refused(self, tmp_path, monkeypatch):
        # Guessing at a realtime audio schema fails in hard-to-debug ways, so an
        # unrecognised protocol is an error rather than a silent fallback.
        path = _providers_file(tmp_path, live={**LIVE_BLOCK, "protocol": "something_new"})
        monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)
        with pytest.raises(VoiceConfigError, match="Unsupported live protocol"):
            load_live_config("gemini")

    def test_non_websocket_url_is_refused(self, tmp_path, monkeypatch):
        path = _providers_file(tmp_path, live={**LIVE_BLOCK, "ws_url": "https://example.test"})
        monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)
        with pytest.raises(VoiceConfigError, match="no valid live ws_url"):
            load_live_config("gemini")

    def test_unknown_provider_is_refused(self, providers):
        with pytest.raises(VoiceConfigError):
            load_live_config("not-a-provider")


class TestSessionCap:
    def test_caller_cap_lowers_the_configured_one(self, providers):
        assert load_live_config("gemini", max_session_seconds=60).max_session_seconds == 60

    def test_caller_cap_cannot_raise_the_configured_one(self, providers):
        # A deployment must not be able to ask for a longer session than the
        # server allows.
        assert load_live_config("gemini", max_session_seconds=9999).max_session_seconds == 300


class TestVoiceProviders:
    def test_lists_provider_with_key_state(self, providers, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setattr(voice_config, "key_source", lambda _pid: "env")
        listed = voice_providers()
        assert [p["provider_id"] for p in listed] == ["gemini"]
        assert listed[0]["key_available"] is True
        assert listed[0]["key_env_var"] == "GEMINI_API_KEY"
        assert listed[0]["voices"] == ["Puck", "Kore"]

    def test_reports_missing_key(self, providers, monkeypatch):
        monkeypatch.setattr(voice_config, "key_source", lambda _pid: "none")
        assert voice_providers()[0]["key_available"] is False

    def test_omits_providers_without_live_support(self, tmp_path, monkeypatch):
        path = _providers_file(tmp_path, live=None)
        monkeypatch.setattr("src.config.provider_registry._providers_path", lambda: path)
        assert voice_providers() == []
