"""AI Studio Builder endpoints — conversational agent/tool/function/workflow generation."""

import json
import re
from typing import Any, AsyncGenerator, Literal

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.auth import require_user, CurrentUser
from src.api.builder_models import BuilderTask, ModelChoice, choose_model
from src.api.builder_prompts import get_builder_prompt
from src.api.chatbot_page import (
    THEMES,
    default_chatbot_html,
    ensure_config_contract,
    ensure_markdown_support,
    harmonize_brand,
    normalize_theme,
    page_defects,
    validate_page,
)
from src.config.config_loader import get_config_loader
from src.config.provider_registry import ProviderResolutionError, resolve_openai_endpoint

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/builder", tags=["builder"])

BuilderType = Literal["agent", "tool", "function", "workflow"]

# A full single-file chat UI plus a reasoning model's thinking tokens
FRONTEND_MAX_TOKENS = 16384


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class BuilderChatRequest(BaseModel):
    builder_type: BuilderType = Field(description="What to build: agent, tool, function, workflow")
    message: str = Field(description="The user's latest message")
    history: list[ChatMessage] = Field(default_factory=list, description="Previous conversation turns")
    provider_id: str = Field(default="openrouter", description="Provider ID from api-providers config")
    # Empty means "let the server pick the best available" — see builder_models.
    model_id: str = Field(default="", description="Model ID; empty selects the best available")


class BuilderGenerateRequest(BaseModel):
    builder_type: BuilderType
    history: list[ChatMessage] = Field(description="Full conversation history")
    provider_id: str = Field(default="")
    model_id: str = Field(default="")


class BuilderGenerateResponse(BaseModel):
    builder_type: BuilderType
    config: dict | str = Field(description="Generated config (dict for agent/tool/workflow, str for function code)")
    raw: str = Field(description="Raw LLM output")


class ModelInfo(BaseModel):
    model_id: str
    provider_id: str
    provider_name: str
    display_name: str


class AvailableModelsResponse(BaseModel):
    models: list[ModelInfo]


class ChatbotPlanRequest(BaseModel):
    prompt: str
    provider_id: str = ""
    model_id: str = ""


class RawApiNormalizeRequest(BaseModel):
    raw_api: str
    specification: str = ""
    provider_id: str = ""
    model_id: str = ""


class BuilderApplyRequest(BaseModel):
    plan: dict


class FrontendChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class FrontendGenerateRequest(BaseModel):
    prompt: str
    workflow_id: str
    title: str = "AI Chatbot"
    greeting: str = "Hi, how can I help?"
    provider_id: str = ""
    model_id: str = ""
    history: list[FrontendChatMessage] = Field(default_factory=list)
    # "themed" restyles the built-in page (its chat always works); "custom" asks
    # the model for a whole HTML document, which is far more likely to break.
    mode: Literal["themed", "custom"] = "themed"
    theme: str = "midnight"


class FrontendGenerateResponse(BaseModel):
    html: str
    summary: str
    model_id: str
    provider_id: str
    used_fallback: bool = False
    mode: str = "themed"
    # The design the model produced, so the Studio can show what it chose.
    design: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_builder_model(body: Any, task: BuilderTask) -> ModelChoice:
    """Fill in ``provider_id``/``model_id`` for a builder task.

    Builder work is one-shot and high-leverage, so an unpinned request is routed
    to the strongest model that is actually reachable rather than to a cheap
    per-endpoint default. A model the caller named explicitly is left alone.

    Mutates ``body`` so the ~25 downstream uses of ``body.model_id`` need no
    change and cannot drift from the decision made here.
    """
    choice = choose_model(
        task,
        requested_provider=str(getattr(body, "provider_id", "") or ""),
        requested_model=str(getattr(body, "model_id", "") or ""),
    )
    body.provider_id = choice.provider_id
    if choice.model_id:
        body.model_id = choice.model_id
    logger.info(
        "builder_model_selected",
        task=task,
        provider=choice.provider_id,
        model=choice.model_id,
        escalated=choice.escalated,
        reason=choice.reason,
    )
    return choice


def _get_provider_credentials(provider_id: str) -> tuple[str, str, bool]:
    """Resolve (base_url, api_key, ready) for OpenAI-compatible builder calls.

    ``ready`` is False when the provider requires a key that is not configured —
    callers with a local fallback use it; callers without one should 400.
    Unknown or endpoint-less providers raise 400 instead of silently falling
    back to OpenRouter.
    """
    try:
        base_url, api_key, auth_required = resolve_openai_endpoint(provider_id)
    except ProviderResolutionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not base_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider '{provider_id}' has no OpenAI-compatible base_url configured",
        )
    ready = bool(api_key) or not auth_required
    return base_url, api_key or "", ready


async def _stream_llm(
    base_url: str,
    api_key: str,
    model_id: str,
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    """Stream tokens from an OpenAI-compatible LLM endpoint as SSE data lines."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_id,
        "messages": messages,
        "stream": True,
        "temperature": 0.4,
        "max_tokens": 4096,
    }

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        ) as response:
            if response.status_code != 200:
                error_body = await response.aread()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"LLM provider error {response.status_code}: {error_body.decode()[:500]}",
                )
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    yield "data: [DONE]\n\n"
                    return
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"]
                    token = delta.get("content", "")
                    if token:
                        yield f"data: {json.dumps({'token': token})}\n\n"
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


async def _call_llm_sync(
    base_url: str,
    api_key: str,
    model_id: str,
    messages: list[dict],
    max_tokens: int = 4096,
) -> tuple[str, bool]:
    """Call an LLM without streaming.

    Returns (content, truncated). ``truncated`` is True when the provider
    stopped because the token budget ran out — the caller must not treat a
    half-finished document as usable output.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_id,
        "messages": messages,
        "stream": False,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM provider error {response.status_code}: {response.text[:500]}",
            )
        data = response.json()
        try:
            choice = data["choices"][0]
            content = choice["message"].get("content")
        except (KeyError, IndexError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="LLM provider returned an unexpected response shape.",
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="LLM provider returned an empty response.",
            )
        truncated = str(choice.get("finish_reason") or "").lower() == "length"
        return content, truncated


def _extract_json_from_text(text: str) -> dict | None:
    """Extract the last JSON code block from LLM output."""
    matches = re.findall(r"```json\s*(.*?)```", text, re.DOTALL)
    if matches:
        try:
            return json.loads(matches[-1].strip())
        except json.JSONDecodeError:
            pass
    # Try bare JSON object
    match = re.search(r"(\{[\s\S]*\})", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return None


def _extract_python_from_text(text: str) -> str | None:
    """Extract the last Python code block from LLM output."""
    matches = re.findall(r"```python\s*(.*?)```", text, re.DOTALL)
    if matches:
        return matches[-1].strip()
    return None


_FENCE_OPEN_RE = re.compile(r"^\s*```[^\n]*\n", re.IGNORECASE)
_FENCE_CLOSE_RE = re.compile(r"\n\s*```\s*$")


def _looks_like_html(value: str) -> bool:
    lowered = value.lower()
    return "<html" in lowered or "<!doctype html" in lowered


def _strip_code_fences(value: str) -> str:
    """Remove markdown fences the model wrapped around the document.

    A truncated response leaves the opening fence with no closing one, so
    fence-pair matching alone lets ```html leak into the deployed page.
    """
    stripped = value.strip()
    stripped = _FENCE_OPEN_RE.sub("", stripped, count=1)
    stripped = _FENCE_CLOSE_RE.sub("", stripped)
    # A bare language word can survive when the fence had no newline after it
    if stripped[:5].lower() in {"html\n", "html\r"}:
        stripped = stripped[5:]
    return stripped.strip()


def _extract_html_from_text(text: str) -> str | None:
    """Extract a deployable HTML document from model output."""
    # Complete fenced blocks first — last one wins (models often explain, then emit)
    for candidate in reversed(re.findall(r"```[^\n]*\n(.*?)```", text, re.DOTALL)):
        stripped = _strip_code_fences(candidate)
        if _looks_like_html(stripped):
            return stripped

    # Unterminated fence (truncated output) or no fence at all
    stripped = _strip_code_fences(text)
    if _looks_like_html(stripped):
        return stripped
    return None


def _ensure_frontend_contract(html: str) -> str:
    """Ensure generated frontends keep runtime config and markdown support."""
    html = ensure_config_contract(html)
    return ensure_markdown_support(html)


def _fallback_plan(prompt: str) -> dict:
    base_id = re.sub(r"[^a-z0-9_]+", "_", prompt.lower()).strip("_")[:40] or "custom_chatbot"
    agent_id = f"{base_id}_agent"
    return {
        "summary": "Starter chatbot plan generated locally because the builder model is not configured.",
        "agents": [
            {
                "id": agent_id,
                "type": "conversable",
                "name": agent_id,
                "description": prompt[:240],
                "system_message": f"You are a helpful chatbot for this goal: {prompt}",
                "llm_config": {"provider_id": "openrouter", "model": "openai/gpt-oss-20b", "temperature": 0.4},
                "human_input_mode": "NEVER",
                "tools": [],
                "max_consecutive_auto_reply": 10,
            }
        ],
        "tools": [],
        "functions": [],
        "workflow": {
            "id": base_id,
            "name": prompt[:60] or "Custom Chatbot",
            "description": prompt,
            "pattern": "single",
            "entry_agent_id": agent_id,
            "enabled": True,
            "workflow_type": "chatbot",
            "persistence": "postgres",
            "topology": {
                "type": "single",
                "nodes": [{"id": agent_id, "agent_id": agent_id, "description": prompt[:160]}],
                "entry_node": agent_id,
            },
            "metadata": {"builder_prompt": prompt},
        },
        "triggers": [
            {"type": "chat", "name": "Public chat", "auth_mode": "public", "greeting": "Hi, how can I help?"}
        ],
        "missing_secrets": ["OPENROUTER_API_KEY"],
    }


def _coerce_tool_config(config: dict, raw_api: str, specification: str) -> dict:
    """Repair model output into the platform tool schema."""
    settings = config.get("settings") if isinstance(config.get("settings"), dict) else {}
    url = (
        settings.get("api_url")
        or config.get("api_url")
        or config.get("url")
        or (re.search(r"https?://[^\s'\"`]+", raw_api).group(0) if re.search(r"https?://[^\s'\"`]+", raw_api) else "")
    )
    method = (
        settings.get("http_method")
        or config.get("http_method")
        or config.get("method")
        or (re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\b", raw_api, re.I).group(1).upper() if re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\b", raw_api, re.I) else "GET")
    )
    name = config.get("name") or config.get("operation_id") or "normalized_api_tool"
    tool_id = config.get("id") or re.sub(r"[^a-z0-9_]+", "_", str(name).lower()).strip("_") or "normalized_api_tool"
    description = config.get("description") or specification or "Normalized API tool generated from raw input."
    metadata = settings.get("_swagger_metadata") or config.get("_swagger_metadata") or {}
    if "parameters" not in metadata and config.get("parameters"):
        metadata["parameters"] = config["parameters"]
    return {
        "id": tool_id,
        "name": name,
        "description": description,
        "entrypoint": "src.tools.api_tool_executor:execute_api_tool",
        "enabled": bool(config.get("enabled", True)),
        "settings": {
            **settings,
            "type": "api",
            "api_url": url,
            "http_method": str(method).upper(),
            "auth_type": settings.get("auth_type") or config.get("auth_type") or "none",
            "timeout": settings.get("timeout") or 30,
            "forward_user_context": settings.get("forward_user_context") or False,
            "_swagger_metadata": metadata,
            "_raw_source": raw_api,
        },
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/chat")
async def builder_chat(
    request: Request,
    body: BuilderChatRequest,
) -> StreamingResponse:
    """
    Conversational AI builder — streams tokens via SSE.

    Frontend should consume `data: {"token": "..."}` lines and concatenate them.
    A `data: [DONE]` line signals completion.
    """
    _resolve_builder_model(body, "chat")
    system_prompt = get_builder_prompt(body.builder_type)
    base_url, api_key, ready = _get_provider_credentials(body.provider_id)
    if not ready:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"API key not configured for provider '{body.provider_id}'",
        )

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for msg in body.history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": body.message})

    logger.info(
        "builder_chat_started",
        builder_type=body.builder_type,
        provider=body.provider_id,
        model=body.model_id,
        history_length=len(body.history),
    )

    return StreamingResponse(
        _stream_llm(base_url, api_key, body.model_id, messages),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/generate", response_model=BuilderGenerateResponse)
async def builder_generate(
    request: Request,
    body: BuilderGenerateRequest,
) -> BuilderGenerateResponse:
    """
    Finalize a builder conversation into a complete config or Python code.

    Adds a system instruction asking the LLM to output only the final config,
    then parses the response and returns the structured result.
    """
    _resolve_builder_model(body, "config")
    system_prompt = get_builder_prompt(body.builder_type)
    base_url, api_key, ready = _get_provider_credentials(body.provider_id)
    if not ready:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"API key not configured for provider '{body.provider_id}'",
        )

    finalize_instruction = (
        "Based on our conversation, produce ONLY the final complete configuration. "
        "Output nothing else — just the JSON or Python code block."
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for msg in body.history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": finalize_instruction})

    logger.info(
        "builder_generate_called",
        builder_type=body.builder_type,
        provider=body.provider_id,
        model=body.model_id,
    )

    raw, _truncated = await _call_llm_sync(base_url, api_key, body.model_id, messages)

    if body.builder_type == "function":
        code = _extract_python_from_text(raw)
        if code is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not extract a Python code block from the LLM response. Try asking the builder to write the function first.",
            )
        return BuilderGenerateResponse(builder_type=body.builder_type, config=code, raw=raw)
    else:
        config = _extract_json_from_text(raw)
        if config is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not extract a JSON config from the LLM response. Continue the conversation until the config is complete.",
            )
        return BuilderGenerateResponse(builder_type=body.builder_type, config=config, raw=raw)


class GraphDigestNode(BaseModel):
    """Allowlisted view of a canvas node.

    Never build this by spreading a node's config: WorkflowCanvas.normalizeConfig
    writes a raw api_key into model_config, and this payload goes to a third-party
    model.
    """

    id: str
    type: str = "agent"
    label: str = ""
    provider_id: str = ""
    model: str = ""
    tools: list[str] = Field(default_factory=list)


class GraphDigest(BaseModel):
    nodes: list[GraphDigestNode] = Field(default_factory=list)
    edges: list[dict[str, str]] = Field(default_factory=list)
    pattern: str = ""


class DiagnosticExplainRequest(BaseModel):
    mode: Literal["explain", "fix", "ask"] = "explain"
    diagnostic: dict | None = None
    question: str | None = None
    graph: GraphDigest = Field(default_factory=GraphDigest)
    provider_id: str = "gemini"
    model_id: str = "gemini-3.5-flash"


def _digest_text(graph: GraphDigest) -> str:
    if not graph.nodes:
        return "The canvas is empty."
    lines = [f"Pattern: {graph.pattern or 'unknown'}", "Nodes:"]
    for node in graph.nodes:
        model = f" using {node.provider_id}/{node.model}" if node.model else ""
        tools = f" tools=[{', '.join(node.tools)}]" if node.tools else ""
        lines.append(f"  - {node.id} ({node.type}) \"{node.label}\"{model}{tools}")
    if graph.edges:
        lines.append("Connections:")
        lines.extend(f"  - {e.get('source', '?')} -> {e.get('target', '?')}" for e in graph.edges)
    return "\n".join(lines)


@router.post("/explain-diagnostic")
async def explain_diagnostic(request: Request, body: DiagnosticExplainRequest) -> StreamingResponse:
    """Explain a workflow problem, or answer a question about the graph.

    The deterministic diagnostics engine decides *what* is wrong; this only puts
    it in plain language and suggests a fix, so a wrong answer here cannot
    invent a problem that does not exist.
    """
    _resolve_builder_model(body, "explain")
    base_url, api_key, ready = _get_provider_credentials(body.provider_id)
    if not ready:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No API key configured for provider '{body.provider_id}'",
        )

    system = (
        "You help someone building an AI agent workflow in a visual studio. "
        "Be concise and concrete: two short paragraphs at most, or a short numbered list. "
        "Refer to nodes by their label. Never invent settings that were not mentioned. "
        "If the finding is a warning rather than an error, say plainly whether it needs fixing."
    )
    digest = _digest_text(body.graph)

    if body.mode == "ask":
        user = f"Workflow:\n{digest}\n\nQuestion: {body.question or 'What does this workflow do?'}"
    else:
        finding = body.diagnostic or {}
        verb = "Explain what this means and why it matters" if body.mode == "explain" else "Give the exact steps to fix this"
        user = (
            f"Workflow:\n{digest}\n\n"
            f"Finding [{finding.get('severity', 'error')}] {finding.get('code', '')}: "
            f"{finding.get('title', '')}\n{finding.get('detail', '')}\n\n{verb}."
        )

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return StreamingResponse(
        _stream_llm(base_url, api_key, body.model_id, messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/models", response_model=AvailableModelsResponse)
async def list_builder_models(request: Request) -> AvailableModelsResponse:
    """List all models available for use in the builder, from configured api-providers."""
    try:
        loader = get_config_loader()
        providers_config = loader.get_config("api_providers")
    except Exception:
        providers_config = {"providers": []}

    models: list[ModelInfo] = []
    for provider in providers_config.get("providers", []):
        if not provider.get("enabled", True):
            continue
        provider_id = provider.get("id", "")
        provider_name = provider.get("name", provider_id)
        for model in provider.get("models", []):
            model_id = model.get("name", "")
            if model_id:
                models.append(
                    ModelInfo(
                        model_id=model_id,
                        provider_id=provider_id,
                        provider_name=provider_name,
                        display_name=f"{model_id} ({provider_name})",
                    )
                )

    # Backstop list for a fresh checkout whose api_providers.json carries no
    # models. Prefer the configured/discovered lists over editing this.
    known_model_ids = {m.model_id for m in models}
    defaults = [
        ("google/gemini-3.6-flash", "openrouter", "OpenRouter", "Gemini 3.6 Flash (OpenRouter)"),
        ("google/gemini-3.5-flash", "openrouter", "OpenRouter", "Gemini 3.5 Flash (OpenRouter)"),
        ("anthropic/claude-opus-5", "openrouter", "OpenRouter", "Claude Opus 5 (OpenRouter)"),
        ("anthropic/claude-sonnet-5", "openrouter", "OpenRouter", "Claude Sonnet 5 (OpenRouter)"),
        ("openai/gpt-5.6-sol", "openrouter", "OpenRouter", "GPT-5.6 Sol (OpenRouter)"),
        ("openai/gpt-5.5", "openrouter", "OpenRouter", "GPT-5.5 (OpenRouter)"),
    ]
    for model_id, provider_id, provider_name, display_name in defaults:
        if model_id not in known_model_ids:
            models.insert(
                0,
                ModelInfo(
                    model_id=model_id,
                    provider_id=provider_id,
                    provider_name=provider_name,
                    display_name=display_name,
                ),
            )

    return AvailableModelsResponse(models=models)


DESIGN_SYSTEM_PROMPT = (
    "You are a product designer choosing the visual identity for a chatbot.\n"
    "Return ONLY a JSON object — no prose, no markdown — with these keys:\n"
    '{"theme": one of ' + ", ".join(f'"{t}"' for t in THEMES) + ",\n"
    ' "brand": {"accent": css colour, "accent-text": css colour readable ON accent,\n'
    '           "bg": page background, "surface": panel background, "panel": sidebar background,\n'
    '           "border": hairline colour, "text": body colour, "muted": secondary text,\n'
    '           "assistant-bubble": reply background, "assistant-border": reply border,\n'
    '           "input-bg", "input-border", "link", "font": a websafe font stack,\n'
    '           "radius": e.g. "12px"},\n'
    ' "title": short product name, "greeting": the assistant\'s opening line,\n'
    ' "suggestions": up to 4 short starter prompts}\n\n'
    "Rules:\n"
    "- Start from the closest theme, then override only what the brief needs.\n"
    "- Colours must be plain hex/rgb/hsl values. No gradients, no images, no CSS beyond a colour.\n"
    "- Body text must stay clearly readable on its background — check accent-text against accent.\n"
    "- Only use fonts that ship with operating systems; there is no network to load one from."
)


def _render_themed_frontend(
    body: FrontendGenerateRequest, design: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Render the built-in page with a generated design applied.

    The page's session handling, composer and API calls come from the template
    that ships with the product, so only presentation can differ — which is why
    this path cannot produce a chatbot whose buttons do nothing.
    """
    theme = normalize_theme(str(design.get("theme") or body.theme))
    # Measured, not trusted: a generated palette that would make text
    # unreadable falls back to the theme's own colours for those values.
    brand, contrast_notes = harmonize_brand(
        theme, design.get("brand") if isinstance(design.get("brand"), dict) else {}
    )
    title = str(design.get("title") or body.title)[:80]
    greeting = str(design.get("greeting") or body.greeting)[:400]
    suggestions = [
        str(item).strip()[:120]
        for item in (design.get("suggestions") or [])
        if str(item).strip()
    ][:4]

    config = {
        "workflow_id": body.workflow_id,
        "name": body.workflow_id,
        "title": title,
        "greeting": greeting,
        "suggestions": suggestions,
        "theme": theme,
        "api_url": "",
    }
    html = default_chatbot_html(
        title=title,
        greeting=greeting,
        workflow_id=body.workflow_id,
        provider_id=body.provider_id,
        model_id=body.model_id,
        theme=theme,
        config=config,
        brand=brand,
    )
    applied = {
        "theme": theme,
        "brand": brand,
        "title": title,
        "greeting": greeting,
        "suggestions": suggestions,
        "contrast_notes": contrast_notes,
    }
    return html, applied


async def _generate_design(
    base_url: str, api_key: str, body: FrontendGenerateRequest
) -> dict[str, Any]:
    messages: list[dict] = [{"role": "system", "content": DESIGN_SYSTEM_PROMPT}]
    for history_item in body.history[-6:]:
        messages.append({"role": history_item.role, "content": history_item.content})
    messages.append(
        {
            "role": "user",
            "content": f"Brief: {body.prompt}\nProduct name hint: {body.title}\nOpening line hint: {body.greeting}",
        }
    )

    # A small JSON token set does not need the frontend's heavyweight model, so
    # this leg gets its own choice — usually a fast one. It falls back to the
    # caller's provider if the design pick lives somewhere unreachable.
    design_model = choose_model("design")
    model_id = design_model.model_id or body.model_id
    design_base_url, design_api_key = base_url, api_key
    if design_model.model_id and design_model.provider_id != body.provider_id:
        try:
            design_base_url, design_api_key, ready = _get_provider_credentials(design_model.provider_id)
            if not ready:
                design_base_url, design_api_key, model_id = base_url, api_key, body.model_id
        except HTTPException:
            design_base_url, design_api_key, model_id = base_url, api_key, body.model_id

    raw, _truncated = await _call_llm_sync(
        design_base_url, design_api_key, model_id, messages, max_tokens=1500
    )
    return _extract_json_from_text(raw) or {}


@router.post("/frontend/generate", response_model=FrontendGenerateResponse)
async def generate_chatbot_frontend(request: Request, body: FrontendGenerateRequest) -> FrontendGenerateResponse:
    """Generate a deployable chatbot frontend.

    ``themed`` (the default) restyles the page that ships with the product, so
    the chat, the composer and the conversation list are the ones that are
    already tested. ``custom`` asks the model for the whole document, which
    allows any layout but has to be checked before it can be deployed.
    """
    _resolve_builder_model(body, "frontend")
    base_url, api_key, ready = _get_provider_credentials(body.provider_id)
    if not ready:
        html, design = _render_themed_frontend(body, {})
        return FrontendGenerateResponse(
            html=html,
            summary="Rendered the built-in chat page with the default theme, because no model API key is configured.",
            model_id=body.model_id,
            provider_id=body.provider_id,
            used_fallback=True,
            mode="themed",
            design=design,
        )

    if body.mode == "themed":
        try:
            design = await _generate_design(base_url, api_key, body)
        except HTTPException as exc:
            html, applied = _render_themed_frontend(body, {})
            return FrontendGenerateResponse(
                html=html,
                summary=f"Used the default theme because the model failed: {exc.detail}",
                model_id=body.model_id,
                provider_id=body.provider_id,
                used_fallback=True,
                mode="themed",
                design=applied,
            )
        html, applied = _render_themed_frontend(body, design)
        return FrontendGenerateResponse(
            html=html,
            summary=(
                f"Styled the built-in chat page: {applied['theme']} theme"
                + (f" with {len(applied['brand'])} custom colours" if applied["brand"] else "")
                + (f" and {len(applied['suggestions'])} starter prompts" if applied["suggestions"] else "")
                + ". Sessions, history and the composer are the tested ones."
                + (
                    f" Kept the theme's colour for {len(applied['contrast_notes'])} value(s) that "
                    f"would have been unreadable: {'; '.join(applied['contrast_notes'])}."
                    if applied["contrast_notes"]
                    else ""
                )
            ),
            model_id=body.model_id,
            provider_id=body.provider_id,
            mode="themed",
            design=applied,
        )

    messages: list[dict] = [
        {
            "role": "system",
            "content": (
                "You are an elite product engineer and interface designer building production chatbot frontends. "
                "Return one complete self-contained HTML document only, preferably inside an html code block. "
                "Use inline CSS and JavaScript. Do not use external libraries, CDNs, build tooling, or explanations. "
                "Assistant responses must support Markdown rendering for headings, bold, lists, links, inline code, and fenced code blocks using a small safe local renderer. "
                "The app must read runtime config from this exact JavaScript expression: window.CHATBOT_CONFIG = __CHATBOT_CONFIG__; "
                "It must create a session with POST cfg.api_url + '/api/v1/sessions' using cfg.workflow_id, then send messages to "
                "POST cfg.api_url + '/api/v1/sessions/' + sessionId + '/messages'. "
                "Make it responsive, polished, accessible, and suitable for a real customer-facing chatbot."
            ),
        }
    ]
    for history_item in body.history[-10:]:
        messages.append({"role": history_item.role, "content": history_item.content})
    messages.append(
        {
            "role": "user",
            "content": (
                f"Build this chatbot frontend.\nTitle: {body.title}\nGreeting: {body.greeting}\n"
                f"Workflow ID: {body.workflow_id}\nUser request: {body.prompt}"
            ),
        }
    )

    def themed_instead(reason: str) -> FrontendGenerateResponse:
        """Fall back to the page that works, rather than returning a broken one."""
        html, applied = _render_themed_frontend(body, {})
        return FrontendGenerateResponse(
            html=html,
            summary=f"{reason} Fell back to the built-in chat page so the chatbot still works.",
            model_id=body.model_id,
            provider_id=body.provider_id,
            used_fallback=True,
            mode="themed",
            design=applied,
        )

    try:
        # A whole page plus a reasoning model's thinking tokens does not fit in
        # the default budget; truncation is what leaves an unterminated ```html
        # fence in the deployed page.
        raw, truncated = await _call_llm_sync(
            base_url, api_key, body.model_id, messages, max_tokens=FRONTEND_MAX_TOKENS
        )
    except HTTPException as exc:
        return themed_instead(f"The selected model failed: {exc.detail}.")

    if truncated:
        return themed_instead("The model ran out of output tokens before finishing the page.")

    html = _extract_html_from_text(raw)
    if html is None:
        return themed_instead("The model did not return a complete HTML document.")

    html = _ensure_frontend_contract(html)

    # The page has to actually function as a chatbot. Custom generation is where
    # dead buttons and chats that never reach the API came from, so a page that
    # fails these checks is replaced rather than handed over to deploy.
    defects = page_defects(html)
    if defects:
        logger.info("builder_custom_frontend_rejected", defects=defects, model_id=body.model_id)
        return themed_instead(f"The generated page would not work: {'; '.join(defects)}")

    warnings = validate_page(html)
    return FrontendGenerateResponse(
        html=html,
        summary=(
            "Generated a custom chatbot page."
            + (f" Warnings: {'; '.join(warnings)}" if warnings else "")
        ),
        model_id=body.model_id,
        provider_id=body.provider_id,
        mode="custom",
        warnings=warnings,
    )


def _known_tool_ids() -> list[str]:
    """Tool ids the plan is allowed to reference, so nothing dangles on apply."""
    try:
        from src.config.tool_registry import get_tool_registry

        return sorted(get_tool_registry().list_tools())
    except Exception:
        return []


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", str(value).lower()).strip("_")
    return slug or fallback


# What the model tends to say, mapped onto what ConversationPattern accepts.
# A value outside the enum makes workflow creation 422, which is one of the ways
# a generated plan ended up creating nothing at all.
_PATTERN_SYNONYMS: dict[str, str] = {
    "chat": "single",
    "chatbot": "single",
    "conversational": "single",
    "conversation": "single",
    "simple": "single",
    "routing": "selector",
    "router": "selector",
    "tree": "selector",
    "hierarchical": "selector",
    "graph": "selector",
    "pipeline": "sequential",
    "chain": "sequential",
    "linear": "sequential",
    "concurrent": "parallel",
    "fanout": "parallel",
}


def _coerce_pattern(value: Any, node_count: int) -> str:
    """Map a model's pattern onto a value ConversationPattern accepts."""
    from src.config.workflow_models import ConversationPattern

    allowed = {member.value for member in ConversationPattern}
    text = _slug(str(value or ""), "")
    if text in allowed:
        return text
    mapped = _PATTERN_SYNONYMS.get(text)
    if mapped in allowed:
        return mapped
    return "single" if node_count <= 1 else "sequential"


def _normalize_plan(plan: dict, prompt: str) -> dict:
    """Repair the plan so it actually applies, instead of failing halfway.

    Models reliably get the shape roughly right and the details wrong: an agent
    id in the topology that no planned agent uses, a tool id that was never
    registered, a missing entry node. Each of those makes `apply` record an
    error and leave the Studio with nothing to show, so they are fixed here
    rather than surfaced.
    """
    plan = dict(plan or {})
    known_tools = set(_known_tool_ids())

    agents: list[dict] = [dict(a) for a in plan.get("agents") or [] if isinstance(a, dict)]
    planned_tool_ids = {
        _slug(t.get("id") or t.get("name") or "", "tool")
        for t in plan.get("tools") or []
        if isinstance(t, dict)
    }
    resolvable = known_tools | planned_tool_ids

    # Tools the model could justify against the brief. Asking for a reason and
    # then enforcing it is what stops the planner attaching the whole catalogue:
    # a prompt rule alone was routinely ignored. A tool the plan defines itself
    # is inherently justified — the model would not have invented it otherwise.
    rationale = plan.get("tool_rationale")
    rationale = rationale if isinstance(rationale, dict) else {}
    justified = {
        str(tool_id)
        for tool_id, reason in rationale.items()
        if isinstance(reason, str) and reason.strip()
    } | planned_tool_ids
    dropped: set[str] = set()

    seen_ids: set[str] = set()
    for index, agent in enumerate(agents):
        agent_id = _slug(agent.get("id") or agent.get("name") or "", f"agent_{index + 1}")
        while agent_id in seen_ids:
            agent_id = f"{agent_id}_{index + 1}"
        seen_ids.add(agent_id)
        agent["id"] = agent_id
        agent.setdefault("type", "conversable")
        agent.setdefault("name", agent_id)
        agent.setdefault("description", prompt[:240])
        # A tool the runtime cannot resolve is worse than none: the agent is told
        # it has a capability it will never be able to call.
        wanted = [t for t in (agent.get("tools") or []) if t in resolvable]
        agent["tools"] = [t for t in wanted if t in justified]
        dropped.update(t for t in wanted if t not in justified)

    if not agents:
        agents = _fallback_plan(prompt)["agents"]
    plan["agents"] = agents

    agents_by_id = {a["id"]: a for a in agents}
    workflow = dict(plan.get("workflow") or {})
    workflow.setdefault("id", _slug(workflow.get("name") or prompt[:40], "custom_chatbot"))
    workflow.setdefault("name", workflow["id"].replace("_", " ").title())
    workflow.setdefault("description", prompt[:240])
    workflow.setdefault("enabled", True)
    workflow.setdefault("workflow_type", "chatbot")

    topology = dict(workflow.get("topology") or {})
    nodes = [dict(n) for n in topology.get("nodes") or [] if isinstance(n, dict)]
    # Drop nodes pointing at agents the plan never defines, and add one for
    # every agent the topology forgot.
    nodes = [n for n in nodes if str(n.get("agent_id") or n.get("id")) in agents_by_id]
    covered = {str(n.get("agent_id") or n.get("id")) for n in nodes}
    for agent in agents:
        if agent["id"] not in covered:
            nodes.append({"id": agent["id"], "agent_id": agent["id"], "description": agent.get("description", "")})

    for node in nodes:
        node.setdefault("id", node.get("agent_id"))
        node.setdefault("agent_id", node.get("id"))
        # Mirror the agent's tools onto the node so the canvas can draw them.
        agent = agents_by_id.get(str(node["agent_id"]))
        if agent and agent.get("tools") and not node.get("tools"):
            node["tools"] = list(agent["tools"])

    entry = str(topology.get("entry_node") or workflow.get("entry_agent_id") or "")
    if entry not in {str(n["id"]) for n in nodes}:
        entry = str(nodes[0]["id"]) if nodes else ""
    topology["nodes"] = nodes
    topology["entry_node"] = entry
    topology.setdefault("edges", [])
    pattern = _coerce_pattern(workflow.get("pattern"), len(nodes))
    topology["type"] = "single" if pattern == "single" else "sequential" if pattern == "sequential" else "graph"

    workflow["pattern"] = pattern
    workflow["topology"] = topology
    workflow["entry_agent_id"] = str(
        agents_by_id.get(entry, {}).get("id")
        or next((n["agent_id"] for n in nodes if n["id"] == entry), entry)
    )
    # A chatbot people will talk to wants memory; without it every turn starts cold.
    workflow.setdefault("memory", {"enabled": True, "retention": "session"})
    metadata = dict(workflow.get("metadata") or {})
    metadata.setdefault("builder_prompt", prompt)
    workflow["metadata"] = metadata
    plan["workflow"] = workflow

    plan.setdefault("tools", [])
    plan.setdefault("functions", [])
    plan.setdefault("triggers", [])
    plan.setdefault("missing_secrets", [])
    if dropped:
        # Surfaced rather than silent, so an over-eager plan is visible in the
        # Studio instead of just quietly producing a leaner agent.
        logger.info("builder_plan_tools_dropped", tools=sorted(dropped))
        plan["dropped_tools"] = sorted(dropped)
    return plan


@router.post("/plan-chatbot")
async def plan_chatbot(request: Request, body: ChatbotPlanRequest) -> dict:
    """Generate a complete chatbot build plan from a natural-language prompt."""
    _resolve_builder_model(body, "plan")
    base_url, api_key, ready = _get_provider_credentials(body.provider_id)
    if not ready:
        return _normalize_plan(_fallback_plan(body.prompt), body.prompt)

    from src.api.builder_context import TOOL_SELECTION_GUIDANCE, render_capability_brief

    messages = [
        {
            "role": "system",
            "content": (
                "You design build plans for a CrewAI-based chatbot platform.\n"
                "Return ONLY a JSON object with keys: summary, agents, tools, functions, workflow, "
                "triggers, missing_secrets.\n\n"
                "agents[]: {id (snake_case), type: 'LlmAgent', name, description, instruction, "
                "tools: [tool_id], llm_config: {provider_id, model, temperature, max_tokens}}\n"
                "workflow: {id, name, description, pattern, entry_agent_id, workflow_type: 'chatbot', "
                "topology: {type, entry_node, nodes: [{id, agent_id, description, tools: [tool_id]}], edges: "
                "[{from_node, to_node}]}}\n\n"
                "Rules:\n"
                "- Every topology node's agent_id MUST be one of the agents you define.\n"
                "- topology.entry_node MUST be one of the node ids.\n"
                "- Only reference tool ids from the catalogue below. Define anything "
                "else under tools[] first.\n"
                "- Repeat each agent's tools on its topology node.\n"
                "- Prefer the fewest agents that do the job. One is fine.\n"
                "\n"
                # The catalogue carries each tool's purpose, not just its id. Without
                # it the model cannot tell what `context_tree` or `detect_pii` are for,
                # so it either ignores the whole set or attaches tools at random.
                + render_capability_brief(include_agents=True, include_workflows=False)
                + "\n\n"
                + TOOL_SELECTION_GUIDANCE
                + "\n\n"
                "tool_rationale: {tool_id: reason} — required whenever any agent has "
                "tools. One short sentence per tool, quoting the part of the brief "
                "that needs it. If you cannot write that sentence, do not attach the "
                "tool.\n"
                "- No prose, no markdown outside the JSON."
            ),
        },
        {"role": "user", "content": body.prompt},
    ]
    raw, _truncated = await _call_llm_sync(base_url, api_key, body.model_id, messages)
    plan = _extract_json_from_text(raw)
    if plan is None:
        raise HTTPException(status_code=422, detail="Could not extract a JSON chatbot plan from the model response")
    normalized = _normalize_plan(plan, body.prompt)
    # Report the model that was actually used, so an escalated choice is visible
    # rather than silent.
    normalized["model_id"] = body.model_id
    normalized["provider_id"] = body.provider_id
    return normalized


@router.post("/normalize-api")
async def normalize_raw_api(request: Request, body: RawApiNormalizeRequest) -> dict:
    """Turn messy API notes, curl commands, or malformed docs into a platform tool config."""
    _resolve_builder_model(body, "tool")
    base_url, api_key, ready = _get_provider_credentials(body.provider_id)
    if not ready:
        guessed_url = re.search(r"https?://[^\s'\"`]+", body.raw_api)
        api_url = guessed_url.group(0) if guessed_url else "https://api.example.com/path"
        method_match = re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\b", body.raw_api, re.I)
        method = method_match.group(1).upper() if method_match else "GET"
        return _coerce_tool_config({
            "id": "normalized_api_tool",
            "name": "normalized_api_tool",
            "description": body.specification or "Normalized API tool generated from raw input.",
            "entrypoint": "src.tools.api_tool_executor:execute_api_tool",
            "enabled": True,
            "settings": {
                "type": "api",
                "api_url": api_url,
                "http_method": method,
                "auth_type": "none",
                "timeout": 30,
                "forward_user_context": False,
                "_raw_source": body.raw_api,
            },
            "warnings": ["Model API key was not configured, so only a heuristic normalization was used."],
        }, body.raw_api, body.specification)

    messages = [
        {
            "role": "system",
            "content": (
                "Normalize raw API input into one tool JSON object for this platform. "
                "Return only JSON matching /api/v1/tools schema. Include detailed parameter metadata in settings._swagger_metadata."
            ),
        },
        {"role": "user", "content": f"Specification:\n{body.specification}\n\nRaw API:\n{body.raw_api}"},
    ]
    raw, _truncated = await _call_llm_sync(base_url, api_key, body.model_id, messages)
    config = _extract_json_from_text(raw)
    if config is None:
        raise HTTPException(status_code=422, detail="Could not extract a JSON tool config from the model response")
    coerced = _coerce_tool_config(config, body.raw_api, body.specification)
    coerced["model_id"] = body.model_id
    coerced["provider_id"] = body.provider_id
    return coerced


@router.post("/apply")
async def apply_builder_plan(request: Request, body: BuilderApplyRequest) -> dict:
    """Apply a generated plan by creating agents, tools, functions, and workflow config."""
    from src.api.routers.agents import create_agent_config
    from src.api.routers.tools import register_tool
    from src.api.routers.functions import create_function_tool, FunctionToolCreateRequest
    from src.api.routers.workflows import create_workflow
    from src.api.models import AgentConfigCreateRequest, ToolRegisterRequest, WorkflowCreateRequest

    from src.api.routers.agents import update_agent_config
    from src.api.routers.workflows import update_workflow
    from src.api.models import AgentConfigUpdateRequest, WorkflowUpdateRequest

    created: dict[str, list[str]] = {"agents": [], "tools": [], "functions": [], "workflows": []}
    updated: dict[str, list[str]] = {"agents": [], "tools": [], "workflows": []}
    errors: list[str] = []
    # Normalize here as well as at plan time: a plan can arrive edited by hand
    # or from an older session, and a missing derived field (entry_agent_id, a
    # pattern outside the enum) would otherwise fail the whole apply.
    plan = _normalize_plan(body.plan, str((body.plan.get("workflow") or {}).get("description") or ""))

    def already_exists(exc: Exception) -> bool:
        return getattr(exc, "status_code", None) == status.HTTP_409_CONFLICT

    # Applying is idempotent. Re-running a plan — or refining one after a first
    # pass — used to fail on "already exists" and leave the Studio with nothing.
    for agent in plan.get("agents", []):
        agent_id = agent.get("id")
        try:
            result = await create_agent_config(request, AgentConfigCreateRequest(**agent))
            created["agents"].append(result.id)
        except Exception as exc:
            if not already_exists(exc):
                errors.append(f"agent {agent_id}: {exc}")
                continue
            try:
                payload = {k: v for k, v in agent.items() if k in AgentConfigUpdateRequest.model_fields}
                await update_agent_config(request, str(agent_id), AgentConfigUpdateRequest(**payload))
                updated["agents"].append(str(agent_id))
            except Exception as update_exc:
                errors.append(f"agent {agent_id}: {update_exc}")

    for tool in plan.get("tools", []):
        tool_id = tool.get("id")
        try:
            result = await register_tool(request, ToolRegisterRequest(**tool))
            created["tools"].append(result.id)
        except Exception as exc:
            if already_exists(exc):
                updated["tools"].append(str(tool_id))
            else:
                errors.append(f"tool {tool_id}: {exc}")

    for function in plan.get("functions", []):
        try:
            result = await create_function_tool(request, FunctionToolCreateRequest(**function))
            created["functions"].append(result.id)
        except Exception as exc:
            errors.append(f"function {function.get('id')}: {exc}")

    workflow = plan.get("workflow")
    workflow_config: dict | None = None
    if workflow:
        workflow_id = str(workflow.get("id") or "")
        try:
            result = await create_workflow(request, WorkflowCreateRequest(**workflow))
            created["workflows"].append(result.id)
            workflow_id = result.id
        except Exception as exc:
            if already_exists(exc):
                try:
                    payload = {k: v for k, v in workflow.items() if k in WorkflowUpdateRequest.model_fields}
                    await update_workflow(request, workflow_id, WorkflowUpdateRequest(**payload))
                    updated["workflows"].append(workflow_id)
                except Exception as update_exc:
                    errors.append(f"workflow {workflow_id}: {update_exc}")
                    workflow_id = ""
            else:
                errors.append(f"workflow {workflow_id}: {exc}")
                workflow_id = ""
        # Returned so the Studio can put the graph on the canvas without a second
        # round trip and without guessing which workflow to load.
        if workflow_id:
            workflow_config = _workflow_config_for_canvas(workflow_id)

    return {"created": created, "updated": updated, "errors": errors, "workflow": workflow_config}


def _workflow_config_for_canvas(workflow_id: str) -> dict | None:
    """The saved workflow as a plain dict, for the Studio to render.

    The registry caches its config, so a workflow created moments ago is not in
    it yet — reload first, or the Studio is handed nothing to draw.
    """
    try:
        from src.config.workflow_registry import get_workflow_registry

        registry = get_workflow_registry()
        registry.reload()
        config = registry.get_workflow(workflow_id)
    except Exception as exc:
        logger.warning("builder_workflow_reload_failed", workflow_id=workflow_id, error=str(exc))
        return None
    if config is None:
        return None
    return config.model_dump(mode="json")
