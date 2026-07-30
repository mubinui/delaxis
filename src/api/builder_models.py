"""Picking the strongest available model for each builder task.

Builder work is one-shot, low-volume and high-leverage: a bad plan or a broken
generated page costs far more than the handful of tokens saved by running it on a
cheap model. The defaults were per-endpoint literals, so a fresh install
generated whole chatbot frontends on ``gpt-oss-20b``.

So the server now chooses. Each task declares a ranked preference of models; the
first one that is actually reachable — provider enabled, key present — wins. A
client can still pin a model explicitly, and that always takes precedence: this
only decides what "auto" means.

Rankings are family-level and ordered by capability for the specific job, not by
price. Keeping them here, rather than scattered across endpoint defaults, means
there is one place to look when a new model ships.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)

BuilderTask = Literal["plan", "config", "tool", "frontend", "design", "chat", "explain"]


@dataclass(frozen=True)
class ModelChoice:
    provider_id: str
    model_id: str
    #: True when this came from the ranked preferences rather than the caller.
    escalated: bool
    #: Why this model, for logging and for the Studio to show.
    reason: str


# Ordered best-first per task. A model string here is matched against what the
# provider config actually offers, so listing a model that is not installed is
# harmless — it is skipped.
#
# Reasoning-heavy tasks (planning a whole chatbot, repairing an API spec into a
# tool schema) rank frontier models first. Frontend generation ranks models that
# reliably emit a single long HTML document without narrating around it.
_PREFERENCES: dict[str, tuple[str, ...]] = {
    # Turning a one-line brief into a full agent/workflow plan.
    "plan": (
        "anthropic/claude-opus-5",
        "openai/gpt-5.6-sol",
        "anthropic/claude-sonnet-5",
        "openai/gpt-5.5",
        "google/gemini-3.1-pro-preview",
        "gemini-3.1-pro-preview",
        "google/gemini-3.6-flash",
        "gemini-3.6-flash",
    ),
    # Emitting a strict JSON config for an agent/workflow/function.
    "config": (
        "anthropic/claude-opus-5",
        "openai/gpt-5.6-sol",
        "anthropic/claude-sonnet-5",
        "openai/gpt-5.5",
        "google/gemini-3.6-flash",
        "gemini-3.6-flash",
    ),
    # Repairing a pasted API spec into the platform tool schema — fiddly,
    # schema-shaped reasoning.
    "tool": (
        "anthropic/claude-opus-5",
        "openai/gpt-5.6-sol",
        "anthropic/claude-sonnet-5",
        "google/gemini-3.1-pro-preview",
        "gemini-3.1-pro-preview",
        "google/gemini-3.6-flash",
        "gemini-3.6-flash",
    ),
    # A whole single-file HTML document; long, structured output.
    "frontend": (
        "anthropic/claude-opus-5",
        "anthropic/claude-sonnet-5",
        "openai/gpt-5.6-sol",
        "google/gemini-3.6-flash",
        "gemini-3.6-flash",
    ),
    # A small JSON design token set — fast models are fine here.
    "design": (
        "anthropic/claude-sonnet-5",
        "google/gemini-3.6-flash",
        "gemini-3.6-flash",
        "openai/gpt-5.6-sol",
        "google/gemini-3.5-flash",
    ),
    # Interactive back-and-forth; latency matters as much as depth.
    "chat": (
        "anthropic/claude-sonnet-5",
        "openai/gpt-5.6-sol",
        "google/gemini-3.6-flash",
        "gemini-3.6-flash",
        "anthropic/claude-opus-5",
    ),
    # Explaining one diagnostic in a sentence or two.
    "explain": (
        "google/gemini-3.6-flash",
        "gemini-3.6-flash",
        "anthropic/claude-sonnet-5",
        "openai/gpt-5.6-sol",
    ),
}


def _available() -> list[tuple[str, str]]:
    """(provider_id, model_id) pairs that could actually be called right now.

    A provider without a key is skipped rather than escalated to, so auto-select
    can never turn a working build into an authentication error.
    """
    from src.config.provider_registry import key_source, list_llm_providers

    pairs: list[tuple[str, str]] = []
    for provider in list_llm_providers():
        provider_id = str(provider.get("id") or "")
        if not provider_id:
            continue
        auth = provider.get("auth") or {}
        if auth.get("required", True) and key_source(provider_id) == "none":
            continue
        for entry in provider.get("models", []) or []:
            name = entry.get("name") if isinstance(entry, dict) else entry
            if name:
                pairs.append((provider_id, str(name)))
    return pairs


def choose_model(
    task: BuilderTask,
    *,
    requested_provider: str = "",
    requested_model: str = "",
) -> ModelChoice:
    """Resolve the model for a builder task.

    Three cases, in decreasing order of how much the caller asked for:

    1. A model was named — honoured exactly. The Studio still lets you pin one and
       this must not second-guess a deliberate choice.
    2. A provider was named but no model — the provider is kept and only the model
       is chosen, from that provider's own list. Silently moving the request to a
       different provider would swallow a typo'd or unconfigured provider id that
       the caller needs to see as an error.
    3. Neither — free choice across everything that is reachable.
    """
    if requested_model:
        return ModelChoice(
            provider_id=requested_provider or "openrouter",
            model_id=requested_model,
            escalated=False,
            reason="pinned by caller",
        )

    available = _available()
    ranked = _PREFERENCES.get(task, _PREFERENCES["config"])

    if requested_provider:
        scoped = [pair for pair in available if pair[0] == requested_provider]
        for preferred in ranked:
            for provider_id, model_id in scoped:
                if model_id == preferred:
                    return ModelChoice(
                        provider_id=provider_id,
                        model_id=model_id,
                        escalated=True,
                        reason=f"best available from '{requested_provider}' for {task}",
                    )
        if scoped:
            provider_id, model_id = scoped[0]
            return ModelChoice(
                provider_id=provider_id,
                model_id=model_id,
                escalated=True,
                reason=f"first usable from '{requested_provider}' for {task}",
            )
        # Unknown, disabled, or keyless provider: hand it back untouched so the
        # caller's own credential check reports the real problem.
        return ModelChoice(
            provider_id=requested_provider,
            model_id="",
            escalated=False,
            reason=f"provider '{requested_provider}' has no usable model",
        )

    for preferred in ranked:
        for provider_id, model_id in available:
            if model_id == preferred:
                return ModelChoice(
                    provider_id=provider_id,
                    model_id=model_id,
                    escalated=True,
                    reason=f"best available for {task}",
                )

    # Nothing on the preference list is installed. Fall back to the first usable
    # model rather than failing — a working build on an unranked model beats none.
    if available:
        provider_id, model_id = available[0]
        logger.info(
            "builder_model_no_preferred_match",
            task=task,
            using=model_id,
            provider=provider_id,
        )
        return ModelChoice(
            provider_id=provider_id,
            model_id=model_id,
            escalated=True,
            reason=f"no preferred model configured; first usable for {task}",
        )

    # No provider has a key. Let the caller's own defaults surface the error.
    return ModelChoice(
        provider_id=requested_provider or "openrouter",
        model_id="",
        escalated=False,
        reason="no provider with a usable key",
    )


def ranked_models(task: BuilderTask) -> list[str]:
    """The preference order for a task, for docs and the Studio's tooltip."""
    return list(_PREFERENCES.get(task, ()))
