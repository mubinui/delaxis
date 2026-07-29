"""Which LLM parameters each CrewAI route actually honours.

CrewAI's provider classes are Pydantic models with ``extra='ignore'``, so an
unsupported sampling parameter is accepted and then silently discarded. Without
this map the studio would happily show a "frequency penalty" field for a
provider that throws it away, which is worse than not offering it at all.

The parameter sets below were introspected from the installed crewai package
(``crewai.llms.providers.*.completion``) rather than copied from docs, so they
track the version actually in use.

Note that the *effective* route is decided at call time: a native provider whose
SDK is not installed falls back to the OpenAI-compatible route (see
``provider_registry.compat_fallback``). Capability filtering must therefore key
off the route being attempted, not the provider's declared prefix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Superset used when a route is unknown — matches crewai.LLM's own LiteLLM path.
_FULL_PARAMS: tuple[str, ...] = (
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "frequency_penalty",
    "presence_penalty",
    "seed",
    "stop",
    "timeout",
    "reasoning_effort",
    "response_format",
)

# Introspected from OpenAICompletion.model_fields (crewai 1.14.4)
_OPENAI_PARAMS: tuple[str, ...] = (
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "frequency_penalty",
    "presence_penalty",
    "seed",
    "stop",
    "timeout",
    "reasoning_effort",
    "response_format",
)


@dataclass(frozen=True)
class RouteCapabilities:
    """What a single CrewAI route accepts."""

    crewai_provider: str
    supported_llm_params: tuple[str, ...]
    # Providers spell the output cap differently; gemini's native class uses
    # max_output_tokens where OpenAI-style routes use max_tokens.
    output_token_param: str = "max_tokens"


# Keyed by the crewai provider name passed to LLM(provider=...).
CREWAI_ROUTE_PARAMS: dict[str, RouteCapabilities] = {
    "openai": RouteCapabilities("openai", _OPENAI_PARAMS),
    "openrouter": RouteCapabilities("openrouter", _OPENAI_PARAMS),
    "deepseek": RouteCapabilities("deepseek", _OPENAI_PARAMS),
    "ollama": RouteCapabilities("ollama", _OPENAI_PARAMS),
    "ollama_chat": RouteCapabilities("ollama_chat", _OPENAI_PARAMS),
    "hosted_vllm": RouteCapabilities("hosted_vllm", _OPENAI_PARAMS),
    "cerebras": RouteCapabilities("cerebras", _OPENAI_PARAMS),
    "dashscope": RouteCapabilities("dashscope", _OPENAI_PARAMS),
    # Native SDK routes. These are only reachable when the matching extra is
    # installed; otherwise the registry falls back to the openai route above.
    "anthropic": RouteCapabilities(
        "anthropic",
        ("temperature", "top_p", "max_tokens", "timeout", "response_format"),
    ),
    "gemini": RouteCapabilities(
        "gemini",
        ("temperature", "top_p", "top_k", "max_output_tokens", "timeout", "response_format"),
        output_token_param="max_output_tokens",
    ),
    "azure": RouteCapabilities("azure", _OPENAI_PARAMS),
}

# Agent constructor settings, verified present and non-deprecated in crewai
# 1.14.4. Deliberately excludes agent-level max_tokens (declared but never read)
# and the deprecated reasoning / multimodal / allow_code_execution.
AGENT_PARAMS: tuple[str, ...] = (
    "max_iter",
    "max_rpm",
    "max_execution_time",
    "max_retry_limit",
    "allow_delegation",
    "respect_context_window",
    "cache",
    "verbose",
    "inject_date",
    "use_system_prompt",
)


def route_capabilities(crewai_provider: str | None) -> RouteCapabilities:
    """Capabilities for a route, falling back to the permissive superset."""
    if not crewai_provider:
        return RouteCapabilities("unknown", _FULL_PARAMS)
    return CREWAI_ROUTE_PARAMS.get(
        crewai_provider, RouteCapabilities(crewai_provider, _FULL_PARAMS)
    )


def filter_llm_params(
    crewai_provider: str | None, params: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Keep only parameters this route honours, renaming the output-token key.

    Returns ``(kept, dropped_keys)``. Callers should log the dropped keys so a
    setting that cannot take effect is visible rather than mysterious.
    """
    caps = route_capabilities(crewai_provider)
    supported = set(caps.supported_llm_params)
    kept: dict[str, Any] = {}
    dropped: list[str] = []

    for key, value in params.items():
        if value is None:
            continue
        # Accept either spelling of the output cap and emit the route's own.
        if key in {"max_tokens", "max_output_tokens"}:
            target = caps.output_token_param
            if target in supported:
                kept[target] = value
            else:
                dropped.append(key)
            continue
        if key in supported:
            kept[key] = value
        else:
            dropped.append(key)

    return kept, sorted(dropped)
