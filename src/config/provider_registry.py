"""Provider registry — makes ``provider_id`` authoritative for LLM routing.

Resolves a provider id (from ``configs/api_providers.json``, including providers
added at runtime through the studio UI) into everything needed to call the
model: a model name, the CrewAI provider to route through, a base URL, and a key.

CrewAI is always given an *explicit* ``provider`` kwarg plus a bare model name.
That skips CrewAI's model-name validation, which otherwise rejects anything not
matching a known naming pattern (``qwen-plus`` under ``openai/`` for example)
and falls through to LiteLLM — a package this project does not depend on.

Two routing modes per provider:

- **Native** (``litellm_prefix`` set): routed through CrewAI's own provider
  integration, e.g. ``ollama`` or ``deepseek``. Self-hosted natives pass
  ``litellm_base_url``.
- **OpenAI-compatible** (no prefix): routed through CrewAI's ``openai``
  provider pointed at the provider's ``base_url`` — this is how LM Studio,
  DashScope (Qwen), Zhipu, Moonshot, and any custom endpoint are supported.

Key resolution: inline ``api_key`` (pasted in the UI) wins, then the
``auth.env_var`` environment variable.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProviderResolutionError(ValueError):
    """Raised when a provider id cannot be resolved to a usable LLM route."""


# Local endpoints accept any key; send a placeholder so an unrelated key from
# the environment is never forwarded to someone's localhost server.
PLACEHOLDER_API_KEY = "not-needed"


@dataclass(frozen=True)
class ResolvedLLM:
    provider_id: str
    model: str
    crewai_provider: str
    base_url: str | None
    api_key: str | None
    openai_endpoint: str | None
    auth_required: bool
    native: bool


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _providers_path() -> Path:
    """Same file the api-providers CRUD endpoints write, read fresh per call."""
    cwd_path = Path("configs") / "api_providers.json"
    if cwd_path.exists():
        return cwd_path
    return _PROJECT_ROOT / "configs" / "api_providers.json"


def _load_providers() -> list[dict[str, Any]]:
    path = _providers_path()
    if not path.exists():
        return []
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    providers = config.get("providers", [])
    return providers if isinstance(providers, list) else []


def list_llm_providers() -> list[dict[str, Any]]:
    """All enabled LLM providers, raw config dicts."""
    return [
        provider
        for provider in _load_providers()
        if provider.get("enabled", True) and provider.get("type", "llm") == "llm"
    ]


def _find_provider(provider_id: str) -> dict[str, Any]:
    for provider in _load_providers():
        if provider.get("id") == provider_id:
            if not provider.get("enabled", True):
                raise ProviderResolutionError(f"Provider is disabled: {provider_id}")
            if provider.get("type", "llm") != "llm":
                raise ProviderResolutionError(f"Provider is not an LLM provider: {provider_id}")
            return provider
    raise ProviderResolutionError(f"Unknown LLM provider: {provider_id}")


def _resolve_base_url(provider: dict[str, Any]) -> str | None:
    env_name = provider.get("base_url_env")
    if env_name:
        from_env = os.environ.get(str(env_name))
        if from_env:
            return from_env.rstrip("/")
    base = provider.get("base_url") or provider.get("default_base_url")
    return base.rstrip("/") if base else None


def _resolve_api_key(provider: dict[str, Any]) -> str | None:
    inline = provider.get("api_key")
    if inline:
        return str(inline)
    auth = provider.get("auth") or {}
    env_var = auth.get("env_var") or provider.get("api_key_env")
    if env_var:
        return os.environ.get(str(env_var)) or None
    return None


def _auth_required(provider: dict[str, Any]) -> bool:
    auth = provider.get("auth")
    if not auth:
        return False
    return bool(auth.get("required", True))


def _strip_prefix(model: str, prefix: str) -> str:
    return model[len(prefix) + 1:] if model.startswith(f"{prefix}/") else model


def resolve_llm(provider_id: str, model: str) -> ResolvedLLM:
    """Resolve provider + model into a CrewAI route.

    Raises ProviderResolutionError for unknown/disabled providers or an
    OpenAI-compatible provider without a base URL — never silently falls back.
    """
    provider = _find_provider(provider_id)
    model = str(model or "").strip()
    if not model:
        raise ProviderResolutionError(f"No model specified for provider: {provider_id}")

    openai_endpoint = _resolve_base_url(provider)
    api_key = _resolve_api_key(provider)
    auth_required = _auth_required(provider)
    prefix = provider.get("litellm_prefix") or None

    # A model entry may pin the exact route (e.g. the openrouter/vllm seeds).
    for entry in provider.get("models", []):
        if isinstance(entry, dict) and entry.get("name") == model and entry.get("litellm_string"):
            pinned = str(entry["litellm_string"])
            pinned_prefix, _, pinned_model = pinned.partition("/")
            if pinned_model:
                prefix = prefix or pinned_prefix
                model = _strip_prefix(pinned, prefix) if prefix else pinned_model
            break

    if prefix:
        crewai_provider = prefix
        model_name = _strip_prefix(model, prefix)
        env_name = provider.get("base_url_env")
        base_url = (os.environ.get(str(env_name)) if env_name else None) or provider.get("litellm_base_url") or None
        base_url = base_url.rstrip("/") if base_url else None
        native = True
    else:
        # OpenAI-compatible endpoint driven entirely by base_url
        if not openai_endpoint:
            raise ProviderResolutionError(
                f"Provider '{provider_id}' has no base_url; an OpenAI-compatible endpoint is required"
            )
        crewai_provider = "openai"
        model_name = _strip_prefix(model, "openai")
        base_url = openai_endpoint
        native = False
        if not api_key and not auth_required:
            api_key = PLACEHOLDER_API_KEY

    return ResolvedLLM(
        provider_id=provider_id,
        model=model_name,
        crewai_provider=crewai_provider,
        base_url=base_url,
        api_key=api_key,
        openai_endpoint=openai_endpoint,
        auth_required=auth_required,
        native=native,
    )


def compat_fallback(resolved: ResolvedLLM) -> ResolvedLLM | None:
    """Recast a native route as an OpenAI-compatible one.

    Used when CrewAI's native provider SDK is not installed (Gemini needs
    ``crewai[google-genai]``, for example) but the provider also publishes an
    OpenAI-compatible endpoint.
    """
    if not resolved.native or not resolved.openai_endpoint:
        return None
    api_key = resolved.api_key
    if not api_key and not resolved.auth_required:
        api_key = PLACEHOLDER_API_KEY
    return ResolvedLLM(
        provider_id=resolved.provider_id,
        model=resolved.model,
        crewai_provider="openai",
        base_url=resolved.openai_endpoint,
        api_key=api_key,
        openai_endpoint=resolved.openai_endpoint,
        auth_required=resolved.auth_required,
        native=False,
    )


def resolve_openai_endpoint(provider_id: str) -> tuple[str | None, str | None, bool]:
    """(base_url, api_key, auth_required) for raw OpenAI-compatible HTTP callers."""
    provider = _find_provider(provider_id)
    return _resolve_base_url(provider), _resolve_api_key(provider), _auth_required(provider)
