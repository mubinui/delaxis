"""AI Studio Builder endpoints — conversational agent/tool/function/workflow generation."""

import json
import re
from html import escape
from typing import AsyncGenerator, Literal

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.auth import require_user, CurrentUser
from src.api.builder_prompts import get_builder_prompt
from src.api.chatbot_page import (
    MARKDOWN_STYLE,
    MARKDOWN_SCRIPT,
    ensure_config_contract,
    ensure_markdown_support,
    safe_json,
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
    model_id: str = Field(default="openai/gpt-5.6-sol", description="Model ID to use for generation")


class BuilderGenerateRequest(BaseModel):
    builder_type: BuilderType
    history: list[ChatMessage] = Field(description="Full conversation history")
    provider_id: str = Field(default="openrouter")
    model_id: str = Field(default="openai/gpt-5.6-sol")


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
    provider_id: str = "openrouter"
    model_id: str = "openai/gpt-oss-20b"


class RawApiNormalizeRequest(BaseModel):
    raw_api: str
    specification: str = ""
    provider_id: str = "openrouter"
    model_id: str = "openai/gpt-oss-20b"


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
    provider_id: str = "openrouter"
    model_id: str = "google/gemini-3.6-flash"
    history: list[FrontendChatMessage] = Field(default_factory=list)


class FrontendGenerateResponse(BaseModel):
    html: str
    summary: str
    model_id: str
    provider_id: str
    used_fallback: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _fallback_frontend(body: FrontendGenerateRequest) -> str:
    title = escape(body.title)
    # Greeting lands inside a JS string literal, so it needs a JS escape, not an HTML one
    greeting_js = safe_json(body.greeting)
    prompt = escape(body.prompt)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <script>window.CHATBOT_CONFIG = __CHATBOT_CONFIG__;</script>
  <title>{title}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f7fb; color: #172033; }}
    main {{ min-height: 100vh; display: grid; grid-template-columns: minmax(280px, 390px) 1fr; }}
    aside {{ padding: 32px; background: #172033; color: white; display: flex; flex-direction: column; justify-content: space-between; }}
    h1 {{ margin: 0; font-size: 34px; line-height: 1.05; letter-spacing: 0; }}
    p {{ color: #cbd5e1; line-height: 1.6; }}
    .tag {{ display: inline-flex; align-items: center; width: max-content; border: 1px solid rgba(255,255,255,.18); border-radius: 999px; padding: 7px 10px; font-size: 12px; color: #dbeafe; margin-bottom: 18px; }}
    section {{ display: flex; align-items: center; justify-content: center; padding: 28px; }}
    .chat {{ width: min(760px, 100%); height: min(760px, calc(100vh - 56px)); background: white; border: 1px solid #d8deea; border-radius: 8px; box-shadow: 0 22px 70px rgba(15,23,42,.12); display: flex; flex-direction: column; overflow: hidden; }}
    .bar {{ padding: 16px 18px; border-bottom: 1px solid #e5e9f1; font-weight: 800; }}
    .messages {{ flex: 1; overflow: auto; padding: 20px; display: flex; flex-direction: column; gap: 12px; }}
    .msg {{ max-width: 84%; padding: 12px 14px; border-radius: 8px; line-height: 1.5; white-space: pre-wrap; font-size: 14px; }}
    .assistant {{ align-self: flex-start; background: #eef3ff; color: #172033; }}
    .user {{ align-self: flex-end; background: #2563eb; color: white; }}
{MARKDOWN_STYLE}
    form {{ display: flex; gap: 10px; padding: 14px; border-top: 1px solid #e5e9f1; }}
    input {{ flex: 1; border: 1px solid #cbd5e1; border-radius: 6px; padding: 12px; font: inherit; }}
    button {{ border: 0; border-radius: 6px; background: #172033; color: white; font-weight: 800; padding: 0 18px; cursor: pointer; }}
    button:disabled {{ opacity: .55; cursor: wait; }}
    @media (max-width: 820px) {{ main {{ grid-template-columns: 1fr; }} aside {{ display: none; }} section {{ padding: 12px; }} .chat {{ height: calc(100vh - 24px); }} }}
  </style>
</head>
<body>
  <main>
    <aside>
      <div>
        <div class="tag">Flash deployed chatbot</div>
        <h1>{title}</h1>
        <p>{prompt}</p>
      </div>
      <p>Workflow: <strong id="workflow-label"></strong></p>
    </aside>
    <section>
      <div class="chat">
        <div class="bar">{title}</div>
        <div id="messages" class="messages"></div>
        <form id="form">
          <input id="input" autocomplete="off" placeholder="Type your message..." />
          <button id="send" type="submit">Send</button>
        </form>
      </div>
    </section>
  </main>
  <script>
    const cfg = window.CHATBOT_CONFIG || {{}};
    const messages = document.getElementById('messages');
    const input = document.getElementById('input');
    const send = document.getElementById('send');
    document.getElementById('workflow-label').textContent = cfg.workflow_id || '';
    let sessionId = null;
{MARKDOWN_SCRIPT}
    function add(role, text) {{
      const bubble = document.createElement('div');
      bubble.className = 'msg ' + role;
            if (role === 'assistant') {{
                bubble.classList.add('md-content');
                bubble.innerHTML = renderMarkdown(text);
            }} else {{
                bubble.textContent = text;
            }}
      messages.appendChild(bubble);
      messages.scrollTop = messages.scrollHeight;
    }}
    async function ensureSession() {{
      if (sessionId) return sessionId;
      const response = await fetch(cfg.api_url + '/api/v1/sessions', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ workflow_id: cfg.workflow_id, user_id: 'flash-user', metadata: {{ deployment: cfg.name }} }})
      }});
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      sessionId = data.session_id;
      return sessionId;
    }}
    add('assistant', cfg.greeting || {greeting_js});
    document.getElementById('form').addEventListener('submit', async (event) => {{
      event.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      add('user', text);
      send.disabled = true;
      try {{
        const sid = await ensureSession();
        const response = await fetch(cfg.api_url + '/api/v1/sessions/' + sid + '/messages', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ message: text, max_turns: 10, metadata: {{ provider_id: cfg.provider_id, model_id: cfg.model_id }} }})
        }});
        if (!response.ok) throw new Error(await response.text());
        const data = await response.json();
        add('assistant', data.response || 'No response');
      }} catch (error) {{
        add('assistant', 'Error: ' + error.message);
      }} finally {{
        send.disabled = false;
        input.focus();
      }}
    }});
  </script>
</body>
</html>"""


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


@router.post("/frontend/generate", response_model=FrontendGenerateResponse)
async def generate_chatbot_frontend(request: Request, body: FrontendGenerateRequest) -> FrontendGenerateResponse:
    """Generate a deployable custom chatbot frontend as a single HTML file."""
    base_url, api_key, ready = _get_provider_credentials(body.provider_id)
    if not ready:
        return FrontendGenerateResponse(
            html=_fallback_frontend(body),
            summary="Generated a local premium fallback frontend because the model API key is not configured.",
            model_id=body.model_id,
            provider_id=body.provider_id,
            used_fallback=True,
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

    try:
        # A whole page plus a reasoning model's thinking tokens does not fit in
        # the default budget; truncation is what leaves an unterminated ```html
        # fence in the deployed page.
        raw, truncated = await _call_llm_sync(
            base_url, api_key, body.model_id, messages, max_tokens=FRONTEND_MAX_TOKENS
        )
    except HTTPException as exc:
        return FrontendGenerateResponse(
            html=_fallback_frontend(body),
            summary=f"Generated a local fallback frontend because the selected model failed: {exc.detail}",
            model_id=body.model_id,
            provider_id=body.provider_id,
            used_fallback=True,
        )
    if truncated:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "The model ran out of output tokens before finishing the page. "
                "Try a shorter prompt or a model with a larger output budget."
            ),
        )
    html = _extract_html_from_text(raw)
    if html is None:
        raise HTTPException(status_code=422, detail="Could not extract a complete HTML document from the model response")
    # Boundary check only: the injected markdown renderer legitimately contains
    # triple backticks (it parses fenced code blocks), so scanning the whole
    # document would false-positive on every page.
    if html.lstrip().startswith("```") or html.rstrip().endswith("```"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The model response still contained markdown fences after extraction.",
        )
    html = _ensure_frontend_contract(html)
    page_warnings = validate_page(html)
    summary = "Generated a custom deployable chatbot frontend."
    if page_warnings:
        summary = f"{summary} Warnings: {'; '.join(page_warnings)}"
    return FrontendGenerateResponse(
        html=html,
        summary=summary,
        model_id=body.model_id,
        provider_id=body.provider_id,
    )


@router.post("/plan-chatbot")
async def plan_chatbot(request: Request, body: ChatbotPlanRequest) -> dict:
    """Generate a complete chatbot build plan from a natural-language prompt."""
    base_url, api_key, ready = _get_provider_credentials(body.provider_id)
    if not ready:
        return _fallback_plan(body.prompt)

    messages = [
        {
            "role": "system",
            "content": (
                "You are designing a production AI chatbot platform build plan. "
                "Return only JSON with keys: summary, agents, tools, functions, workflow, triggers, missing_secrets. "
                "Agents must match /api/v1/agents schema. Tools must match /api/v1/tools schema. "
                "Workflow must match /api/v1/workflows schema with topology. "
                "Prefer simple, shippable configs over explanations."
            ),
        },
        {"role": "user", "content": body.prompt},
    ]
    raw, _truncated = await _call_llm_sync(base_url, api_key, body.model_id, messages)
    plan = _extract_json_from_text(raw)
    if plan is None:
        raise HTTPException(status_code=422, detail="Could not extract a JSON chatbot plan from the model response")
    return plan


@router.post("/normalize-api")
async def normalize_raw_api(request: Request, body: RawApiNormalizeRequest) -> dict:
    """Turn messy API notes, curl commands, or malformed docs into a platform tool config."""
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
    return _coerce_tool_config(config, body.raw_api, body.specification)


@router.post("/apply")
async def apply_builder_plan(request: Request, body: BuilderApplyRequest) -> dict:
    """Apply a generated plan by creating agents, tools, functions, and workflow config."""
    from src.api.routers.agents import create_agent_config
    from src.api.routers.tools import register_tool
    from src.api.routers.functions import create_function_tool, FunctionToolCreateRequest
    from src.api.routers.workflows import create_workflow
    from src.api.models import AgentConfigCreateRequest, ToolRegisterRequest, WorkflowCreateRequest

    created: dict[str, list[str]] = {"agents": [], "tools": [], "functions": [], "workflows": []}
    errors: list[str] = []
    plan = body.plan

    for agent in plan.get("agents", []):
        try:
            result = await create_agent_config(request, AgentConfigCreateRequest(**agent))
            created["agents"].append(result.id)
        except Exception as exc:
            errors.append(f"agent {agent.get('id')}: {exc}")

    for tool in plan.get("tools", []):
        try:
            result = await register_tool(request, ToolRegisterRequest(**tool))
            created["tools"].append(result.id)
        except Exception as exc:
            errors.append(f"tool {tool.get('id')}: {exc}")

    for function in plan.get("functions", []):
        try:
            result = await create_function_tool(request, FunctionToolCreateRequest(**function))
            created["functions"].append(result.id)
        except Exception as exc:
            errors.append(f"function {function.get('id')}: {exc}")

    workflow = plan.get("workflow")
    if workflow:
        try:
            result = await create_workflow(request, WorkflowCreateRequest(**workflow))
            created["workflows"].append(result.id)
        except Exception as exc:
            errors.append(f"workflow {workflow.get('id')}: {exc}")

    return {"created": created, "errors": errors}
