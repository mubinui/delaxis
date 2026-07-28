"""Tests for model capability inference."""

from src.config.llm_provider import ProviderConfig, ProviderType
from src.config.model_capabilities import infer_model_capabilities


def test_gpt_4o_capabilities_include_streaming_tools_vision_and_schema() -> None:
    capabilities = infer_model_capabilities("openai/gpt-4o-2024-11-20", ProviderType.OPENROUTER)

    assert capabilities.streaming is True
    assert capabilities.tool_calling is True
    assert capabilities.vision is True
    assert capabilities.json_schema is True
    assert capabilities.max_context >= 128_000


def test_reasoning_models_expose_reasoning_trace_flag() -> None:
    capabilities = infer_model_capabilities("deepseek/deepseek-r1-0528", ProviderType.OPENROUTER)

    assert capabilities.reasoning_trace is True
    assert capabilities.tool_calling is True
    assert capabilities.json_schema is True


def test_audio_models_expose_audio_flags() -> None:
    capabilities = infer_model_capabilities("openai/gpt-4o-realtime-preview", ProviderType.OPENROUTER)

    assert capabilities.audio_in is True
    assert capabilities.audio_out is True


def test_provider_config_uses_active_model_for_capabilities() -> None:
    config = ProviderConfig(
        provider=ProviderType.VLLM,
        model_name="openai/gpt-oss-20b-128k",
    )

    capabilities = config.get_model_capabilities()

    assert capabilities.streaming is True
    assert capabilities.tool_calling is True
    assert capabilities.max_context == 128_000
    assert config.check_function_calling_support() is True


def test_unknown_model_defaults_are_conservative() -> None:
    capabilities = infer_model_capabilities("local/custom-small-model", ProviderType.OLLAMA)

    assert capabilities.streaming is True
    assert capabilities.tool_calling is False
    assert capabilities.vision is False
    assert capabilities.reasoning_trace is False
    assert capabilities.max_context == 8192

def test_current_generation_models_support_tool_calling():
    """Family-level markers must keep working as providers ship version bumps —
    a version-specific list silently disables tools on every new release."""
    for model in [
        "gpt-5.6-sol",
        "gpt-5.5",
        "claude-opus-5",
        "claude-sonnet-5",
        "gemini-3.6-flash",
        "deepseek-v4-pro",
        "qwen3.7-plus",
        "glm-5.2",
        "kimi-k3",
        "llama3.3",
    ]:
        assert infer_model_capabilities(model).tool_calling is True, model


def test_current_generation_context_windows_are_not_the_8k_default():
    for model in ["gpt-5.6-sol", "gemini-3.6-flash", "claude-opus-5", "glm-5.2", "kimi-k3"]:
        assert infer_model_capabilities(model).max_context > 100_000, model


def test_unknown_local_model_stays_conservative():
    capabilities = infer_model_capabilities("local/custom-small-model")
    assert capabilities.tool_calling is False
    assert capabilities.max_context == 8192
