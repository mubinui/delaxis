"""Resolving a provider's realtime-voice route from configs/api_providers.json.

The realtime model id and the wire protocol are configuration, not code. Google
has shipped several live model ids under different names, and this project's
catalog is maintained by hand — so a hardcoded id would rot, and rot in the
worst way: a 400 from the provider some weeks after the code was written. Both
live here as data, overridable per environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from src.config.model_capabilities import infer_model_capabilities
from src.config.provider_registry import (
    ProviderResolutionError,
    key_source,
    resolve_api_key,
)

# The only frame encoders implemented. A provider declaring anything else is a
# configuration error rather than a silent fallback, because guessing at a
# realtime audio schema fails in ways that are very hard to debug.
SUPPORTED_PROTOCOLS = ("bidi_generate_content_v1beta",)


class VoiceConfigError(ValueError):
    """Raised when a provider cannot be resolved to a usable realtime route."""


@dataclass(frozen=True)
class LiveVoiceConfig:
    """Everything needed to open one upstream realtime session."""

    provider_id: str
    protocol: str
    ws_url: str
    auth_query_param: str
    model: str
    model_prefix: str
    input_sample_rate: int
    input_mime_type: str
    output_sample_rate: int
    max_session_seconds: int
    voices: tuple[str, ...] = field(default_factory=tuple)

    @property
    def upstream_model(self) -> str:
        """The model id as the upstream API expects it (e.g. ``models/x``)."""
        if self.model_prefix and not self.model.startswith(self.model_prefix):
            return f"{self.model_prefix}{self.model}"
        return self.model


def _live_block(provider_id: str) -> dict[str, Any]:
    from src.config.provider_registry import _find_provider

    try:
        provider = _find_provider(provider_id)
    except ProviderResolutionError as exc:
        raise VoiceConfigError(str(exc)) from exc

    live = provider.get("live")
    if not isinstance(live, dict):
        raise VoiceConfigError(f"Provider '{provider_id}' declares no live voice support")
    if not live.get("enabled", True):
        raise VoiceConfigError(f"Live voice is disabled for provider '{provider_id}'")
    return live


def _resolve_model(live: dict[str, Any], requested: str | None) -> str:
    """Requested model -> env override -> the config default.

    A requested model must appear in the provider's ``live.models`` allow-list.
    The deployed page's config is visitor-editable, so an unchecked value here
    would let anyone point the bridge at an arbitrary (and arbitrarily
    expensive) model.
    """
    entries = [m for m in live.get("models", []) if isinstance(m, dict) and m.get("name")]
    allowed = [str(m["name"]) for m in entries]

    if requested:
        if requested not in allowed:
            raise VoiceConfigError(
                f"Model '{requested}' is not in the live allow-list for this provider"
            )
        return requested

    env_name = live.get("model_env")
    from_env = os.environ.get(str(env_name)) if env_name else None
    if from_env:
        if from_env not in allowed:
            raise VoiceConfigError(
                f"{env_name}='{from_env}' is not in the live allow-list "
                f"({', '.join(allowed) or 'none configured'})"
            )
        return from_env

    default = next((str(m["name"]) for m in entries if m.get("default")), None)
    if default:
        return default
    if allowed:
        return allowed[0]
    raise VoiceConfigError("Provider declares live voice but lists no models")


def load_live_config(
    provider_id: str = "gemini",
    *,
    model: str | None = None,
    max_session_seconds: int | None = None,
) -> LiveVoiceConfig:
    """Build the realtime route for a provider, or raise VoiceConfigError."""
    live = _live_block(provider_id)

    protocol = str(live.get("protocol") or "")
    if protocol not in SUPPORTED_PROTOCOLS:
        raise VoiceConfigError(
            f"Unsupported live protocol '{protocol}' for provider '{provider_id}'"
        )

    ws_url = str(live.get("ws_url") or "")
    if not ws_url.startswith(("wss://", "ws://")):
        raise VoiceConfigError(f"Provider '{provider_id}' has no valid live ws_url")

    resolved_model = _resolve_model(live, model)

    # The capability flags in model_capabilities have existed unused since the
    # provider layer was written; this is what they were for. Inferring from the
    # name also means a typo'd model id fails closed rather than opening a
    # billable session against a text-only model.
    capabilities = infer_model_capabilities(resolved_model, provider_id)
    if not (capabilities.audio_in and capabilities.audio_out):
        raise VoiceConfigError(
            f"Model '{resolved_model}' does not look like a realtime audio model"
        )

    inp = live.get("input") or {}
    out = live.get("output") or {}
    configured_cap = int(live.get("max_session_seconds") or 300)
    cap = min(configured_cap, max_session_seconds) if max_session_seconds else configured_cap

    return LiveVoiceConfig(
        provider_id=provider_id,
        protocol=protocol,
        ws_url=ws_url,
        auth_query_param=str(live.get("auth_query_param") or "key"),
        model=resolved_model,
        model_prefix=str(live.get("model_prefix") or ""),
        input_sample_rate=int(inp.get("sample_rate") or 16000),
        input_mime_type=str(inp.get("mime_type") or "audio/pcm;rate=16000"),
        output_sample_rate=int(out.get("sample_rate") or 24000),
        max_session_seconds=max(1, cap),
        voices=tuple(str(v) for v in live.get("voices", []) if v),
    )


def live_api_key(provider_id: str) -> str:
    """The provider key for a realtime session.

    Goes through the normal provider key resolution (inline -> secret store ->
    environment) so a key pasted in the Studio works for voice too.
    """
    key = resolve_api_key(provider_id)
    if not key:
        raise VoiceConfigError(
            f"No API key available for provider '{provider_id}'; set its environment "
            "variable or paste a key in the Studio"
        )
    return key


def voice_providers() -> list[dict[str, Any]]:
    """Providers advertising live voice, for the Studio deploy form."""
    from src.config.provider_registry import list_llm_providers

    result: list[dict[str, Any]] = []
    for provider in list_llm_providers():
        live = provider.get("live")
        if not isinstance(live, dict) or not live.get("enabled", True):
            continue
        provider_id = str(provider.get("id"))
        models = [
            str(m["name"])
            for m in live.get("models", [])
            if isinstance(m, dict) and m.get("name")
        ]
        result.append(
            {
                "provider_id": provider_id,
                "name": str(provider.get("name") or provider_id),
                "models": models,
                "voices": [str(v) for v in live.get("voices", []) if v],
                "key_available": key_source(provider_id) != "none",
                "key_env_var": str((provider.get("auth") or {}).get("env_var") or ""),
            }
        )
    return result
