"""Unit tests for provider-aware LLM resolution in the CrewAI runtime."""

import json

import pytest

from src.config import provider_registry
from src.crewai_runtime.runtime import CrewAIWorkflowRuntime


@pytest.fixture
def runtime():
    # _resolve_llm_model does not touch instance state, so skip __init__
    return object.__new__(CrewAIWorkflowRuntime)


@pytest.fixture
def providers_file(tmp_path, monkeypatch):
    def _write(providers):
        path = tmp_path / "api_providers.json"
        path.write_text(json.dumps({"version": "2.0", "providers": providers}), encoding="utf-8")
        monkeypatch.setattr(provider_registry, "_providers_path", lambda: path)
        return path

    return _write


def test_provider_id_routes_through_registry(runtime, monkeypatch):
    monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
    llm = runtime._resolve_llm_model({"provider_id": "ollama", "model": "llama3.1", "temperature": 0.2})
    assert llm.model == "llama3.1"
    assert llm.base_url == "http://localhost:11434/v1"


def test_openai_compatible_model_names_are_accepted(runtime, monkeypatch):
    """qwen-plus/glm-4.5 do not match CrewAI's model-name patterns; the explicit
    provider kwarg is what keeps them from falling through to (absent) LiteLLM."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    monkeypatch.setenv("ZHIPUAI_API_KEY", "sk-test")
    for provider_id, model in [("dashscope", "qwen-plus"), ("zhipu", "glm-4.5")]:
        llm = runtime._resolve_llm_model({"provider_id": provider_id, "model": model})
        assert not isinstance(llm, str), f"{provider_id} fell back to a bare model string"
        assert llm.model == model


def test_gemini_falls_back_to_openai_compatible_endpoint(runtime, monkeypatch):
    """Native Gemini needs crewai[google-genai]; without it the OpenAI-compatible
    endpoint must still produce a working client."""
    monkeypatch.setenv("GEMINI_API_KEY", "sk-test")
    llm = runtime._resolve_llm_model({"provider_id": "gemini", "model": "gemini-2.5-flash"})
    assert not isinstance(llm, str)
    assert llm.model == "gemini-2.5-flash"


def test_openai_compatible_provider_gets_base_url_and_key(runtime, providers_file, monkeypatch):
    providers_file([
        {
            "id": "dashscope",
            "type": "llm",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "auth": {"scheme": "bearer", "env_var": "DASHSCOPE_API_KEY", "required": True},
        }
    ])
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    llm = runtime._resolve_llm_model({"provider_id": "dashscope", "model": "qwen-plus"})
    assert llm.model == "qwen-plus"
    assert llm.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert llm.api_key == "sk-test"


def test_agent_base_url_override_wins(runtime, monkeypatch):
    monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
    llm = runtime._resolve_llm_model(
        {"provider_id": "ollama", "model": "llama3.1", "base_url": "http://gpu-box:11434"}
    )
    # CrewAI normalizes Ollama hosts to the /v1 OpenAI-compatible path
    assert llm.base_url == "http://gpu-box:11434/v1"


def test_agent_api_key_env_override_wins(runtime, providers_file, monkeypatch):
    providers_file([
        {
            "id": "p1",
            "type": "llm",
            "base_url": "https://x.example/v1",
            "auth": {"scheme": "bearer", "env_var": "P1_KEY", "required": True},
        }
    ])
    monkeypatch.setenv("P1_KEY", "provider-key")
    monkeypatch.setenv("AGENT_KEY", "agent-key")
    llm = runtime._resolve_llm_model({"provider_id": "p1", "model": "m", "api_key_env": "AGENT_KEY"})
    assert llm.api_key == "agent-key"


def test_no_provider_id_keeps_legacy_prefixing(runtime, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    result = runtime._resolve_llm_model({"model": "google/gemma-3-27b-it"})
    assert result == "openrouter/google/gemma-3-27b-it"


def test_no_provider_and_no_model_uses_env_default(runtime, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    result = runtime._resolve_llm_model({})
    assert result == "openrouter/google/gemma-3-27b-it"


def test_unknown_provider_falls_back_to_legacy_without_crashing(runtime, monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    result = runtime._resolve_llm_model({"provider_id": "ghost", "model": "acme/some-model"})
    assert result == "openrouter/acme/some-model"


def test_already_prefixed_legacy_model_untouched(runtime):
    result = runtime._resolve_llm_model({"model": "ollama/llama3.1"})
    assert result == "ollama/llama3.1"
