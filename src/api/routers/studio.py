"""Studio orchestration endpoints for the premium CrewAI workbench."""

from __future__ import annotations

import time

import httpx
from typing import Any
from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, status

from src.config.config_loader import get_config_loader
from src.audit_logging import get_logger

logger = get_logger(__name__)
from src.config.provider_registry import ProviderResolutionError, resolve_openai_endpoint

router = APIRouter(prefix="/api/v1/studio", tags=["studio"])


class LiveLlmTestRequest(BaseModel):
    """Payload for executing instant live LLM evaluations."""
    provider: str = "openrouter"
    model: str = "google/gemini-3.5-flash-lite"
    api_key: str | None = None
    system_prompt: str = "You are a helpful AI assistant."
    user_prompt: str = "Hello"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=32768)


class LiveLlmTestResponse(BaseModel):
    """Execution output from the live testing API."""
    response: str
    provider: str
    model: str
    latency_ms: int
    token_usage: dict[str, int]
    estimated_cost_usd: float
    status: str = "success"


def _safe_config(name: str, fallback: Any) -> Any:
    try:
        return get_config_loader().get_config(name)
    except Exception:
        return fallback


@router.get("/state")
async def get_studio_state() -> dict[str, Any]:
    """Return one compact snapshot for the CrewAI canvas UI."""
    from src.api.routers.deployments import _load_config as _load_deployments_config

    workflows_config = _safe_config("workflows", {"workflows": []})
    agents_config = _safe_config("agents", {"agents": []})
    tools_config = _safe_config("tools", {"tools": []})
    providers_config = _safe_config("api_providers", {"providers": []})
    try:
        deployments_config = _load_deployments_config()
    except Exception:
        deployments_config = {"deployments": []}

    workflows = workflows_config.get("workflows", [])
    agents = agents_config.get("agents", [])
    tools = tools_config.get("tools", [])
    providers = providers_config.get("providers", [])
    deployments = deployments_config.get("deployments", [])

    return {
        "runtime": "crewai",
        "product": "Delaxis",
        "counts": {
            "workflows": len(workflows),
            "agents": len(agents),
            "tools": len(tools),
            "providers": len(providers),
            "deployments": len(deployments),
        },
        "capabilities": {
            "canvas": True,
            "drag_drop_nodes": True,
            "workflow_save_load": True,
            "dry_run": True,
            "streaming_execution": True,
            "memory": True,
            "knowledge": True,
            "guardrails": True,
            "deployment_center": True,
            "live_llm_testing": True,
        },
        "node_catalog": [
            {"type": "trigger", "label": "Manual Trigger", "accent": "trigger"},
            {"type": "trigger", "label": "Chat Trigger", "accent": "trigger"},
            {"type": "agent", "label": "CrewAI Agent", "accent": "agent"},
            {"type": "router", "label": "Flow Router", "accent": "flow"},
            {"type": "tool", "label": "Tool/API Action", "accent": "tool"},
            {"type": "tool", "label": "Memory Store", "accent": "memory"},
            {"type": "tool", "label": "Knowledge Source", "accent": "knowledge"},
            {"type": "router", "label": "Guardrail", "accent": "guardrail"},
            {"type": "output", "label": "Output", "accent": "output"},
        ],
    }


@router.post("/test-llm", response_model=LiveLlmTestResponse)
async def test_live_llm(request: LiveLlmTestRequest) -> LiveLlmTestResponse:
    """Execute a real-time LLM call against the selected provider.

    Uses the provider registry's OpenAI-compatible endpoint over plain HTTP.
    This previously called litellm, which is not a dependency of this project,
    so the tester failed for every provider with "No module named 'litellm'".
    """
    started = time.perf_counter()
    logger.info("live_llm_test_requested", model=request.model, provider=request.provider)

    try:
        base_url, api_key, auth_required = resolve_openai_endpoint(request.provider)
    except ProviderResolutionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if request.api_key and request.api_key.strip():
        api_key = request.api_key.strip()
    if not base_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider '{request.provider}' has no OpenAI-compatible base_url configured",
        )
    if auth_required and not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No API key configured for provider '{request.provider}'",
        )

    # Providers expect their own bare model id; strip a provider prefix if the
    # caller supplied one (e.g. "gemini/gemini-3.5-flash").
    model_id = request.model
    if model_id.startswith(f"{request.provider}/"):
        model_id = model_id[len(request.provider) + 1:]

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_prompt},
        ],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=payload
            )
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:400]}")
            data = response.json()

        content = (data["choices"][0]["message"].get("content") or "").strip()
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
        # Rough indicative figure only; real pricing varies per model.
        cost = (prompt_tokens * 0.0000015) + (completion_tokens * 0.000006)

        return LiveLlmTestResponse(
            response=content,
            provider=request.provider,
            model=request.model,
            latency_ms=round((time.perf_counter() - started) * 1000),
            token_usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
            estimated_cost_usd=round(cost, 6),
        )

    except HTTPException:
        raise
    except Exception as e:
        latency = round((time.perf_counter() - started) * 1000)
        logger.error("live_llm_test_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": f"LLM call to {request.provider}/{request.model} failed",
                "error": str(e),
                "latency_ms": latency,
            },
        ) from e
