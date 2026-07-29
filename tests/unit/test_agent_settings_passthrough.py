"""Agent/LLM settings must survive studio -> API -> config -> runtime.

These settings were previously dropped by LLMConfig's fixed schema and the
runtime's hard allowlists, so a value set in the studio silently did nothing.
"""

import pytest

from src.api.models import AgentConfigCreateRequest
from src.config.agent_models import AgentConfig, AgentRuntimeSettings, LLMConfig
from src.config.provider_capabilities import (
    AGENT_PARAMS,
    filter_llm_params,
    route_capabilities,
)
from src.crewai_runtime.runtime import CrewAIWorkflowRuntime


@pytest.fixture
def runtime():
    return object.__new__(CrewAIWorkflowRuntime)


class TestCapabilityFiltering:
    def test_gemini_gets_its_own_output_token_spelling(self):
        kept, _ = filter_llm_params("gemini", {"max_tokens": 64})
        assert kept == {"max_output_tokens": 64}

    def test_openai_keeps_max_tokens(self):
        kept, _ = filter_llm_params("openai", {"max_tokens": 64})
        assert kept == {"max_tokens": 64}

    def test_unsupported_params_are_reported_not_silently_passed(self):
        """CrewAI provider classes ignore unknown kwargs, so an unsupported
        setting would look applied while doing nothing."""
        kept, dropped = filter_llm_params("anthropic", {"seed": 1, "frequency_penalty": 0.5, "top_p": 0.9})
        assert kept == {"top_p": 0.9}
        assert dropped == ["frequency_penalty", "seed"]

    def test_top_k_is_gemini_only(self):
        assert "top_k" in route_capabilities("gemini").supported_llm_params
        assert "top_k" not in route_capabilities("openai").supported_llm_params

    def test_unknown_route_is_permissive(self):
        kept, dropped = filter_llm_params("something-new", {"temperature": 0.5, "seed": 3})
        assert kept == {"temperature": 0.5, "seed": 3}
        assert dropped == []

    def test_none_values_are_never_forwarded(self):
        kept, dropped = filter_llm_params("openai", {"temperature": None, "top_p": 0.5})
        assert kept == {"top_p": 0.5}
        assert dropped == []

    def test_agent_params_excludes_dead_and_deprecated_crewai_fields(self):
        """agent-level max_tokens is never read by crewai 1.14.4; reasoning,
        multimodal and allow_code_execution are deprecated."""
        for dead in ("max_tokens", "reasoning", "multimodal", "allow_code_execution"):
            assert dead not in AGENT_PARAMS


class TestSamplingParams:
    def test_no_route_means_no_filtering(self, runtime):
        params = runtime._sampling_params({"top_k": 40, "seed": 1})
        assert params == {"top_k": 40, "seed": 1}

    def test_route_filters_and_renames(self, runtime):
        params = runtime._sampling_params({"max_tokens": 32, "top_k": 40, "seed": 1}, "gemini")
        assert params == {"max_output_tokens": 32, "top_k": 40}


class TestAgentParams:
    def test_settings_reach_the_agent_constructor(self, runtime):
        config = AgentConfig(
            id="a", type="conversable", name="A",
            agent_settings=AgentRuntimeSettings(
                max_iter=3, max_retry_limit=1, max_execution_time=45,
                respect_context_window=False, allow_delegation=True,
            ),
        )
        params = runtime._agent_params(config, runtime._effective_model_config(config))
        assert params["max_iter"] == 3
        assert params["max_retry_limit"] == 1
        assert params["max_execution_time"] == 45
        assert params["respect_context_window"] is False
        assert params["allow_delegation"] is True

    def test_defaults_are_preserved_when_nothing_is_set(self, runtime):
        config = AgentConfig(id="a", type="conversable", name="A")
        params = runtime._agent_params(config, {})
        assert params["max_iter"] == 20
        assert params["allow_delegation"] is False

    def test_selector_delegates_by_default(self, runtime):
        config = AgentConfig(id="a", type="conversable", name="A", is_selector=True)
        assert runtime._agent_params(config, {})["allow_delegation"] is True

    def test_explicit_setting_beats_the_is_selector_default(self, runtime):
        config = AgentConfig(
            id="a", type="conversable", name="A", is_selector=True,
            agent_settings=AgentRuntimeSettings(allow_delegation=False),
        )
        params = runtime._agent_params(config, runtime._effective_model_config(config))
        assert params["allow_delegation"] is False

    def test_legacy_model_config_override_still_works(self, runtime):
        """max_iter historically travelled inside the untyped override."""
        config = AgentConfig(
            id="a", type="conversable", name="A",
            model_config={"provider_id": "openai", "model": "gpt-4o", "max_iter": 7},
        )
        params = runtime._agent_params(config, runtime._effective_model_config(config))
        assert params["max_iter"] == 7


class TestEndToEndRoundTrip:
    def test_studio_payload_survives_to_runtime(self, runtime):
        payload = AgentConfigCreateRequest(
            id="round_trip", type="conversable", name="RoundTrip",
            llm_config={
                "provider_id": "gemini", "model": "gemini-3.5-flash",
                "temperature": 0.2, "max_tokens": 64, "top_p": 0.8, "seed": 11,
            },
            agent_settings={"max_iter": 3, "max_execution_time": 45},
        ).model_dump()

        config = AgentConfig(**payload)
        merged = runtime._effective_model_config(config)

        assert merged["max_iter"] == 3
        assert merged["top_p"] == 0.8
        assert merged["seed"] == 11
        assert runtime._agent_params(config, merged)["max_execution_time"] == 45
        assert runtime._sampling_params(merged, "gemini")["max_output_tokens"] == 64

    def test_llm_config_sampling_fields_are_not_dropped(self):
        """LLMConfig previously had no home for these, so extra='ignore' ate them."""
        config = LLMConfig(
            provider_id="openai", model="gpt-4o",
            top_p=0.5, seed=3, frequency_penalty=0.2, stop=["END"],
        )
        dumped = config.model_dump(exclude_none=True)
        assert dumped["top_p"] == 0.5
        assert dumped["seed"] == 3
        assert dumped["frequency_penalty"] == 0.2
        assert dumped["stop"] == ["END"]

    def test_is_selector_round_trips_through_the_api_schema(self):
        """Previously dropped on create, making allow_delegation un-settable."""
        payload = AgentConfigCreateRequest(
            id="a", type="conversable", name="A", is_selector=True
        ).model_dump()
        assert AgentConfig(**payload).is_selector is True
