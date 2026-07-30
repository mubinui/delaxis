"""Live voice endpoints: an authenticated ticket, then one WebSocket per session.

The split is deliberate. FastAPI's HTTP middleware — JWT validation and rate
limiting — does not run on WebSocket connections, so the socket is not where
policy can be enforced. Instead the ordinary HTTP ticket endpoint is the choke
point: it is authenticated, logged and rate limited like every other route, and
the socket accepts nothing but a short-lived single-use ticket it minted.

Native realtime voice talks to the model directly. The canvas workflow, its
tools and its routing do NOT run in voice mode — only the persona carries over.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from src.api.auth import CurrentUser, get_current_user
from src.api.rate_limiting import endpoint_rate_limit
from src.api.session_manager import get_session_manager
from src.api.voice import protocol as p
from src.api.voice import tickets
from src.api.voice.bridge import VoiceUpstreamError, run_bridge
from src.api.voice.config import VoiceConfigError, live_api_key, load_live_config, voice_providers
from src.api.voice.persona import build_system_instruction
from src.config.settings import get_settings

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/voice", tags=["voice"])

# Process-wide ceiling on concurrent realtime sessions. Never a queue: a caller
# waiting in line is a caller holding an open microphone.
_capacity: asyncio.Semaphore | None = None
_capacity_size = 0


def _semaphore() -> asyncio.Semaphore:
    global _capacity, _capacity_size
    configured = max(1, int(get_settings().voice.max_concurrent))
    if _capacity is None or _capacity_size != configured:
        _capacity = asyncio.Semaphore(configured)
        _capacity_size = configured
    return _capacity


class TicketRequest(BaseModel):
    session_id: str
    deployment: str | None = None


class TicketResponse(BaseModel):
    ticket: str
    expires_in: int
    ws_path: str
    input_sample_rate: int
    output_sample_rate: int
    max_session_seconds: int


@router.get("/providers")
async def list_voice_providers() -> dict[str, Any]:
    """Providers advertising live voice, and whether a key is configured."""
    settings = get_settings()
    return {"enabled": settings.voice.enabled, "providers": voice_providers()}


@router.get("/health")
async def voice_health() -> dict[str, Any]:
    """Whether a voice session could be opened right now, and why not."""
    settings = get_settings()
    if not settings.voice.enabled:
        return {"ok": False, "detail": "Live voice is disabled (DELAXIS_VOICE_ENABLED=false)"}
    try:
        config = load_live_config("gemini", max_session_seconds=settings.voice.max_session_seconds)
        live_api_key(config.provider_id)
    except VoiceConfigError as exc:
        return {"ok": False, "detail": str(exc)}
    return {
        "ok": True,
        "provider_id": config.provider_id,
        "model": config.model,
        "input_sample_rate": config.input_sample_rate,
        "output_sample_rate": config.output_sample_rate,
        "max_session_seconds": config.max_session_seconds,
    }


def _resolve_voice_settings(deployment: str | None) -> tuple[Any, str, str, str, int]:
    """(live_config, api_key, system_prompt, voice_name, max_seconds) for a session.

    Everything here comes from server-side state — the deployment record or the
    provider config — never from the client.
    """
    settings = get_settings()
    if not settings.voice.enabled:
        raise VoiceConfigError("Live voice is disabled")

    provider_id = "gemini"
    model = ""
    voice_name = ""
    system_prompt = ""
    cap = int(settings.voice.max_session_seconds)

    if deployment:
        from src.api.routers.deployments import deployment_voice_config

        record = deployment_voice_config(deployment)
        if record is None or not record.enabled:
            raise VoiceConfigError("Voice is not enabled for this deployment")
        provider_id = record.provider_id or provider_id
        model = record.model
        voice_name = record.voice_name
        system_prompt = record.system_prompt
        cap = min(cap, max(1, int(record.max_session_seconds)))

    config = load_live_config(provider_id, model=model or None, max_session_seconds=cap)
    key = live_api_key(config.provider_id)
    return config, key, system_prompt, voice_name, config.max_session_seconds


@router.post("/ticket", response_model=TicketResponse)
@endpoint_rate_limit("6/minute")
async def create_voice_ticket(
    request: Request,
    body: TicketRequest,
    current_user: CurrentUser = Depends(get_current_user),
) -> TicketResponse:
    """Mint a single-use ticket for one voice WebSocket.

    Authorisation is by resource: the caller must name a session that already
    exists, and creating that session went through the normal authenticated
    endpoint. Voice therefore inherits exactly the text chat's auth posture — if
    you can post a message to this session, you can also speak to it.
    """
    try:
        session_uuid = UUID(body.session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid session ID format: {body.session_id}",
        ) from None

    session = await get_session_manager().get_session(session_uuid)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {body.session_id}",
        )

    try:
        config, _key, _prompt, _voice, max_seconds = _resolve_voice_settings(body.deployment)
    except VoiceConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    ticket, ttl = tickets.mint(session_id=str(session_uuid), deployment=body.deployment)
    logger.info(
        "voice_ticket_issued",
        session_id=str(session_uuid),
        deployment=body.deployment,
        username=current_user.username,
        model=config.model,
    )
    return TicketResponse(
        ticket=ticket,
        expires_in=ttl,
        ws_path="/api/v1/voice/ws",
        input_sample_rate=config.input_sample_rate,
        output_sample_rate=config.output_sample_rate,
        max_session_seconds=max_seconds,
    )


@router.websocket("/ws")
async def voice_websocket(websocket: WebSocket, ticket: str = "") -> None:
    """Bridge a browser's microphone to the realtime model for one session."""
    # Every rejection below happens before accept() or before any upstream
    # socket is opened — an unauthorised caller must never cost a billed session.
    try:
        session_id, deployment = tickets.redeem(ticket)
    except tickets.TicketError as exc:
        await websocket.close(code=p.CLOSE_UNAUTHORIZED, reason=str(exc)[:120])
        return

    try:
        config, api_key, system_prompt, voice_name, max_seconds = _resolve_voice_settings(deployment)
    except VoiceConfigError as exc:
        await websocket.close(code=p.CLOSE_UNAUTHORIZED, reason=str(exc)[:120])
        return

    semaphore = _semaphore()
    if semaphore.locked():
        await websocket.close(code=p.CLOSE_CAPACITY, reason="voice capacity reached")
        return

    manager = get_session_manager()
    try:
        session_uuid = UUID(session_id)
    except ValueError:
        await websocket.close(code=p.CLOSE_UNAUTHORIZED, reason="bad session")
        return

    session = await manager.get_session(session_uuid)
    if session is None:
        await websocket.close(code=p.CLOSE_UNAUTHORIZED, reason="session not found")
        return

    instruction = build_system_instruction(
        title=str((session.metadata or {}).get("deployment") or deployment or "this assistant"),
        system_prompt=system_prompt,
        workflow_id=str((session.metadata or {}).get("workflow_id") or ""),
        history=session.conversation_history,
    )

    await semaphore.acquire()
    await websocket.accept()
    stats = None
    try:
        stats = await asyncio.wait_for(
            run_bridge(
                config=config,
                api_key=api_key,
                system_instruction=instruction,
                voice_name=voice_name,
                client_receive=websocket.receive,
                client_send_bytes=websocket.send_bytes,
                client_send_json=websocket.send_json,
            ),
            timeout=max_seconds,
        )
        await _send_quietly(websocket, {"t": p.SERVER_ENDED, "reason": stats.reason})
    except asyncio.TimeoutError:
        await _send_quietly(websocket, {"t": p.SERVER_ENDED, "reason": p.REASON_TIME_LIMIT})
        logger.info("voice_session_time_limit", session_id=session_id, limit=max_seconds)
    except WebSocketDisconnect:
        logger.info("voice_session_disconnected", session_id=session_id)
    except VoiceUpstreamError as exc:
        logger.warning("voice_upstream_failed", session_id=session_id, error=str(exc))
        await _send_quietly(
            websocket, {"t": p.SERVER_ERROR, "code": "upstream", "message": str(exc)[:200]}
        )
    except Exception as exc:
        logger.error("voice_session_failed", session_id=session_id, error=str(exc), exc_info=True)
        await _send_quietly(
            websocket, {"t": p.SERVER_ERROR, "code": "internal", "message": "voice session failed"}
        )
    finally:
        semaphore.release()
        if stats is not None:
            await _persist_transcript(manager, session_uuid, stats, config)
            logger.info(
                "voice_session_ended",
                session_id=session_id,
                reason=stats.reason,
                bytes_in=stats.bytes_in,
                bytes_out=stats.bytes_out,
                turns=stats.turns,
            )
        with contextlib.suppress(Exception):
            await websocket.close()


async def _persist_transcript(manager: Any, session_uuid: UUID, stats: Any, config: Any) -> None:
    """Write the spoken exchange into the session's normal message history."""
    with contextlib.suppress(Exception):
        await manager.record_voice_turn(
            session_uuid,
            user_text=" ".join(stats.user_text),
            agent_text=" ".join(stats.agent_text),
            runtime="gemini_live",
            provider_id=config.provider_id,
            model=config.model,
        )


async def _send_quietly(websocket: WebSocket, payload: dict[str, Any]) -> None:
    """Best-effort send — the peer may already be gone."""
    with contextlib.suppress(Exception):
        await websocket.send_json(payload)
