"""Studio orchestration endpoints for the premium CrewAI workbench."""

from __future__ import annotations

import time
from typing import Any
from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException, status

from src.config.config_loader import get_config_loader
from src.audit_logging import get_logger

logger = get_logger(__name__)
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
        "product": "Open Agent Kit",
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
    """Execute real-time live LLM API evaluation directly through litellm."""
    started = time.perf_counter()
    logger.info("live_llm_test_requested", model=request.model, provider=request.provider)
    
    try:
        import litellm
        
        # Override key if supplied
        extra_kwargs = {}
        if request.api_key and request.api_key.strip():
            if request.provider == "openrouter":
                extra_kwargs["api_key"] = request.api_key.strip()
            elif request.provider == "openai":
                extra_kwargs["api_key"] = request.api_key.strip()
            elif request.provider == "gemini":
                extra_kwargs["api_key"] = request.api_key.strip()
                
        model_id = request.model
        if not model_id.startswith(f"{request.provider}/") and request.provider in {"openrouter", "gemini", "azure"}:
            model_id = f"{request.provider}/{model_id}"
            
        messages = [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_prompt},
        ]
        
        # Set completion options safely
        response = await litellm.acompletion(
            model=model_id,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            **extra_kwargs,
        )
        
        content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        
        prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        total_tokens = getattr(usage, "total_tokens", 0) if usage else 0
        
        # Simple cost fallback calculation
        cost = (prompt_tokens * 0.0000015) + (completion_tokens * 0.000006)
        latency = round((time.perf_counter() - started) * 1000)
        
        return LiveLlmTestResponse(
            response=content,
            provider=request.provider,
            model=request.model,
            latency_ms=latency,
            token_usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
            estimated_cost_usd=round(cost, 6),
        )
        
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
