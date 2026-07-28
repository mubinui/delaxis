"""Unit tests for the LLM provider registry (provider_id -> LiteLLM route)."""

import json

import pytest

from src.config import provider_registry
from src.config.provider_registry import (
    ProviderResolutionError,
    list_llm_providers,
    resolve_llm,
    resolve_openai_endpoint,
)


@pytest.fixture
def providers_file(tmp_path, monkeypatch):
    """Write a providers config to a temp file and point the registry at it."""

    def _write(providers):
        path = tmp_path / "api_providers.json"
        path.write_text(json.dumps({"version": "2.0", "providers": providers}), encoding="utf-8")
        monkeypatch.setattr(provider_registry, "_providers_path", lambda: path)
        return path

    return _write


class TestSeededProviders:
    """Table-driven over the real configs/api_providers.json seeds."""

    @pytest.mark.parametrize(
        "provider_id,model,expected_model,expected_provider,expected_base",
        [
            ("openai", "gpt-4o", "gpt-4o", "openai", "https://api.openai.com/v1"),
            ("gemini", "gemini-2.5-flash", "gemini-2.5-flash", "gemini", None),
            ("deepseek", "deepseek-chat", "deepseek-chat", "deepseek", "https://api.deepseek.com/v1"),
            ("ollama", "llama3.1", "llama3.1", "ollama", "http://localhost:11434/v1"),
            ("lm-studio", "local-model", "local-model", "openai", "http://localhost:1234/v1"),
            ("dashscope", "qwen-plus", "qwen-plus", "openai", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            ("zhipu", "glm-4.5", "glm-4.5", "openai", "https://open.bigmodel.cn/api/paas/v4"),
            ("moonshot", "moonshot-v1-8k", "moonshot-v1-8k", "openai", "https://api.moonshot.cn/v1"),
            ("openrouter", "google/gemma-3-27b-it", "google/gemma-3-27b-it", "openrouter", "https://openrouter.ai/api/v1"),
            # Pinned litellm_string on the model entry keeps the org/model tail
            ("openrouter", "openai/gpt-oss-20b", "openai/gpt-oss-20b", "openrouter", "https://openrouter.ai/api/v1"),
            ("vllm", "openai/gpt-oss-20b", "openai/gpt-oss-20b", "hosted_vllm", "http://localhost:8000/v1"),
        ],
    )
    def test_resolution(self, provider_id, model, expected_model, expected_provider, expected_base, monkeypatch):
        monkeypatch.delenv("VLLM_API_BASE", raising=False)
        monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
        monkeypatch.delenv("LM_STUDIO_API_BASE", raising=False)
        resolved = resolve_llm(provider_id, model)
        assert resolved.model == expected_model
        assert resolved.crewai_provider == expected_provider
        assert resolved.base_url == expected_base

    def test_model_names_are_never_prefixed(self):
        """CrewAI validates prefixed names against naming patterns; bare + explicit
        provider is what makes arbitrary models (qwen-plus, glm-4.5) work."""
        for provider_id, model in [("dashscope", "qwen-plus"), ("zhipu", "glm-4.5"), ("openai", "gpt-4o")]:
            assert "/" not in resolve_llm(provider_id, model).model

    def test_local_providers_do_not_require_auth(self):
        assert resolve_llm("ollama", "llama3.1").auth_required is False
        assert resolve_llm("lm-studio", "m").auth_required is False
        assert resolve_llm("openai", "gpt-4o").auth_required is True

    def test_user_typed_prefix_is_stripped(self):
        assert resolve_llm("openai", "openai/gpt-4o").model == "gpt-4o"
        assert resolve_llm("gemini", "gemini/gemini-2.5-pro").model == "gemini-2.5-pro"

    def test_keyless_local_provider_gets_placeholder_key(self, monkeypatch):
        """Never forward an unrelated key from the environment to localhost."""
        from src.config.provider_registry import PLACEHOLDER_API_KEY

        monkeypatch.delenv("LM_STUDIO_API_KEY", raising=False)
        assert resolve_llm("lm-studio", "m").api_key == PLACEHOLDER_API_KEY

    def test_gemini_has_openai_compatible_fallback_endpoint(self):
        from src.config.provider_registry import compat_fallback

        resolved = resolve_llm("gemini", "gemini-2.5-flash")
        assert resolved.native is True
        fallback = compat_fallback(resolved)
        assert fallback is not None
        assert fallback.crewai_provider == "openai"
        assert fallback.model == "gemini-2.5-flash"
        assert fallback.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"

    def test_compat_route_has_no_fallback(self):
        from src.config.provider_registry import compat_fallback

        assert compat_fallback(resolve_llm("zhipu", "glm-4.5")) is None

    def test_hyphenated_provider_id_is_valid(self):
        from src.config.dynamic_models import ProviderConfig, ProviderType

        provider = ProviderConfig(id="lm-studio", name="LM Studio", type=ProviderType.LLM)
        assert provider.id == "lm-studio"


class TestResolutionErrors:
    def test_unknown_provider_raises(self):
        with pytest.raises(ProviderResolutionError, match="Unknown LLM provider"):
            resolve_llm("does-not-exist", "some-model")

    def test_disabled_provider_raises(self, providers_file):
        providers_file([{"id": "p1", "type": "llm", "enabled": False}])
        with pytest.raises(ProviderResolutionError, match="disabled"):
            resolve_llm("p1", "m")

    def test_tool_provider_raises(self):
        with pytest.raises(ProviderResolutionError, match="not an LLM provider"):
            resolve_llm("duckduckgo", "m")

    def test_openai_compatible_without_base_url_raises(self, providers_file):
        providers_file([{"id": "p1", "type": "llm", "enabled": True}])
        with pytest.raises(ProviderResolutionError, match="base_url"):
            resolve_llm("p1", "m")

    def test_empty_model_raises(self):
        with pytest.raises(ProviderResolutionError, match="No model"):
            resolve_llm("openai", "")


class TestKeyAndBaseUrlResolution:
    def test_inline_api_key_beats_env_var(self, providers_file, monkeypatch):
        providers_file([
            {
                "id": "p1",
                "type": "llm",
                "base_url": "https://x.example/v1",
                "api_key": "inline-key",
                "auth": {"scheme": "bearer", "env_var": "P1_KEY", "required": True},
            }
        ])
        monkeypatch.setenv("P1_KEY", "env-key")
        assert resolve_llm("p1", "m").api_key == "inline-key"

    def test_env_var_fallback(self, providers_file, monkeypatch):
        providers_file([
            {
                "id": "p1",
                "type": "llm",
                "base_url": "https://x.example/v1",
                "auth": {"scheme": "bearer", "env_var": "P1_KEY", "required": True},
            }
        ])
        monkeypatch.setenv("P1_KEY", "env-key")
        assert resolve_llm("p1", "m").api_key == "env-key"
        monkeypatch.delenv("P1_KEY")
        assert resolve_llm("p1", "m").api_key is None

    def test_base_url_env_overrides_configured_url(self, providers_file, monkeypatch):
        providers_file([
            {
                "id": "p1",
                "type": "llm",
                "base_url": "http://localhost:1234/v1",
                "base_url_env": "P1_BASE",
            }
        ])
        monkeypatch.setenv("P1_BASE", "http://gpu-box:9999/v1/")
        resolved = resolve_llm("p1", "m")
        assert resolved.base_url == "http://gpu-box:9999/v1"
        assert resolved.openai_endpoint == "http://gpu-box:9999/v1"

    def test_ui_added_provider_visible_without_restart(self, providers_file):
        path = providers_file([
            {"id": "p1", "type": "llm", "base_url": "https://x.example/v1"},
        ])
        assert [p["id"] for p in list_llm_providers()] == ["p1"]
        # Simulate the api-providers CRUD endpoint appending a provider
        config = json.loads(path.read_text())
        config["providers"].append({"id": "added-later", "type": "llm", "base_url": "https://y.example/v1"})
        path.write_text(json.dumps(config))
        assert [p["id"] for p in list_llm_providers()] == ["p1", "added-later"]
        resolved = resolve_llm("added-later", "m")
        assert (resolved.model, resolved.crewai_provider) == ("m", "openai")


class TestOpenAIEndpoint:
    def test_returns_endpoint_key_and_auth_flag(self, providers_file, monkeypatch):
        providers_file([
            {
                "id": "p1",
                "type": "llm",
                "base_url": "https://x.example/v1",
                "auth": {"scheme": "bearer", "env_var": "P1_KEY", "required": True},
            }
        ])
        monkeypatch.setenv("P1_KEY", "k")
        assert resolve_openai_endpoint("p1") == ("https://x.example/v1", "k", True)
