"""Relay audio between a browser WebSocket and an upstream realtime model.

Two concurrent pumps run for the life of a session: one carries microphone PCM
up, the other carries speaker PCM and transcripts down. Whichever finishes first
ends the session and the other is cancelled.

Implemented against the raw WebSocket protocol rather than a provider SDK. This
is a relay, not a client — an SDK's session abstraction would sit in the way of
a frame-for-frame pass-through, and would duplicate the key handling the
provider registry already owns. The cost is that the frame schema lives here,
which is why it is isolated behind the encode/decode helpers below.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog
import websockets

from src.api.voice import protocol as p
from src.api.voice.config import LiveVoiceConfig

logger = structlog.get_logger(__name__)

# Generous enough for a long model utterance, small enough that a hostile frame
# cannot exhaust memory.
UPSTREAM_MAX_FRAME = 4 * 1024 * 1024
CLIENT_MAX_AUDIO_FRAME = 64 * 1024

# Allow for silence-suppressed bursts and slight clock drift, but not for a
# client replaying audio at many times realtime to run up a bill.
BYTE_BUDGET_SLACK = 1.5
BYTES_PER_SAMPLE = 2


class VoiceUpstreamError(RuntimeError):
    """The upstream realtime service refused or dropped the session."""


@dataclass
class SessionStats:
    bytes_in: int = 0
    bytes_out: int = 0
    turns: int = 0
    reason: str = p.REASON_CLIENT
    user_text: list[str] = field(default_factory=list)
    agent_text: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Upstream frame encoding/decoding. Everything provider-specific lives here.
# --------------------------------------------------------------------------- #


def build_setup_frame(config: LiveVoiceConfig, *, system_instruction: str, voice_name: str = "") -> dict[str, Any]:
    """The first frame the upstream socket expects.

    ``responseModalities`` is placed under ``generationConfig``, which is where
    the API reference puts it. Google's quickstarts have also shown it at the top
    level of ``setup``; if that becomes the required shape, add a new value to
    ``SUPPORTED_PROTOCOLS`` and branch here rather than editing this in place.
    """
    generation_config: dict[str, Any] = {"responseModalities": ["AUDIO"]}
    if voice_name:
        generation_config["speechConfig"] = {
            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}}
        }

    return {
        "setup": {
            "model": config.upstream_model,
            "generationConfig": generation_config,
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            # Transcripts are what let a spoken turn be persisted into the same
            # message history the text chat uses.
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
        }
    }


def encode_audio_chunk(config: LiveVoiceConfig, pcm: bytes) -> dict[str, Any]:
    return {
        "realtimeInput": {
            "audio": {
                "mimeType": config.input_mime_type,
                "data": base64.b64encode(pcm).decode("ascii"),
            }
        }
    }


def encode_audio_stream_end() -> dict[str, Any]:
    return {"realtimeInput": {"audioStreamEnd": True}}


def _iter_audio_parts(server_content: dict[str, Any]) -> list[bytes]:
    chunks: list[bytes] = []
    model_turn = server_content.get("modelTurn") or {}
    for part in model_turn.get("parts", []) or []:
        inline = part.get("inlineData") or part.get("inline_data") or {}
        data = inline.get("data")
        if data:
            with contextlib.suppress(Exception):
                chunks.append(base64.b64decode(data))
    return chunks


# --------------------------------------------------------------------------- #
# The relay
# --------------------------------------------------------------------------- #


async def run_bridge(
    *,
    config: LiveVoiceConfig,
    api_key: str,
    system_instruction: str,
    voice_name: str = "",
    client_receive: Callable[[], Awaitable[dict[str, Any]]],
    client_send_bytes: Callable[[bytes], Awaitable[None]],
    client_send_json: Callable[[dict[str, Any]], Awaitable[None]],
) -> SessionStats:
    """Bridge one browser session to one upstream realtime session.

    The callables are passed in rather than a Starlette WebSocket so this is
    testable against an in-memory stub, and so it stays unaware of the transport.
    """
    stats = SessionStats()

    # The key travels only in this URL, inside this process. It is never logged
    # (structlog calls below deliberately omit the url) and never sent downstream.
    url = f"{config.ws_url}?{config.auth_query_param}={api_key}"

    byte_budget = int(
        config.max_session_seconds
        * config.input_sample_rate
        * BYTES_PER_SAMPLE
        * BYTE_BUDGET_SLACK
    )

    try:
        upstream_cm = websockets.connect(
            url,
            max_size=UPSTREAM_MAX_FRAME,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=10,
        )
    except Exception as exc:  # pragma: no cover - constructor rarely raises
        raise VoiceUpstreamError(str(exc)) from exc

    async with upstream_cm as upstream:
        await upstream.send(json.dumps(build_setup_frame(
            config, system_instruction=system_instruction, voice_name=voice_name,
        )))

        try:
            first_raw = await asyncio.wait_for(upstream.recv(), timeout=15)
        except asyncio.TimeoutError as exc:
            raise VoiceUpstreamError("timed out waiting for upstream setup") from exc
        first = _as_json(first_raw)
        if "setupComplete" not in first and "setup_complete" not in first:
            raise VoiceUpstreamError(f"unexpected first upstream frame: {sorted(first)[:3]}")

        await client_send_json(
            {
                "t": p.SERVER_READY,
                "in_rate": config.input_sample_rate,
                "out_rate": config.output_sample_rate,
            }
        )

        async def pump_up() -> None:
            """Browser -> upstream."""
            while True:
                message = await client_receive()

                data = message.get("bytes")
                if data is not None:
                    if len(data) > CLIENT_MAX_AUDIO_FRAME:
                        logger.warning("voice_audio_frame_oversized", size=len(data))
                        continue
                    stats.bytes_in += len(data)
                    if stats.bytes_in > byte_budget:
                        stats.reason = p.REASON_BYTE_LIMIT
                        return
                    await upstream.send(json.dumps(encode_audio_chunk(config, data)))
                    continue

                text = message.get("text")
                if text is None:
                    # Starlette signals disconnect with a type-only message.
                    stats.reason = p.REASON_CLIENT
                    return
                frame = _as_json(text)
                kind = frame.get("t")
                if kind == p.CLIENT_STOP:
                    await upstream.send(json.dumps(encode_audio_stream_end()))
                elif kind == p.CLIENT_BYE:
                    stats.reason = p.REASON_CLIENT
                    return

        async def pump_down() -> None:
            """Upstream -> browser."""
            async for raw in upstream:
                frame = _as_json(raw)

                server_content = frame.get("serverContent") or frame.get("server_content")
                if server_content:
                    for chunk in _iter_audio_parts(server_content):
                        stats.bytes_out += len(chunk)
                        await client_send_bytes(chunk)

                    inbound = server_content.get("inputTranscription") or server_content.get("input_transcription")
                    if inbound and inbound.get("text"):
                        stats.user_text.append(str(inbound["text"]))
                        await client_send_json({"t": p.SERVER_USER_TEXT, "d": str(inbound["text"])})

                    outbound = server_content.get("outputTranscription") or server_content.get("output_transcription")
                    if outbound and outbound.get("text"):
                        stats.agent_text.append(str(outbound["text"]))
                        await client_send_json({"t": p.SERVER_AGENT_TEXT, "d": str(outbound["text"])})

                    if server_content.get("interrupted"):
                        # Must reach the browser promptly or the model talks over
                        # the user for as long as audio stays queued.
                        await client_send_json({"t": p.SERVER_INTERRUPTED})

                    if server_content.get("turnComplete") or server_content.get("turn_complete"):
                        stats.turns += 1
                        await client_send_json({"t": p.SERVER_TURN_END})
                    continue

                if frame.get("goAway") or frame.get("go_away"):
                    stats.reason = p.REASON_UPSTREAM
                    return

            stats.reason = p.REASON_UPSTREAM

        # asyncio.wait rather than TaskGroup: this package supports Python 3.10,
        # where TaskGroup does not exist. Same shape as session_manager.
        up_task = asyncio.create_task(pump_up(), name="voice-pump-up")
        down_task = asyncio.create_task(pump_down(), name="voice-pump-down")
        try:
            done, pending = await asyncio.wait(
                {up_task, down_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            for task in done:
                # Surface a pump's exception rather than losing it.
                task.result()
        finally:
            for task in (up_task, down_task):
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    return stats


def _as_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}
