"""The audio relay between a browser and the upstream realtime model.

Driven against an in-memory stub of the upstream socket, so the frame encoding,
the barge-in path, the byte budget and — most importantly — the fact that the
provider API key never reaches the client are all covered without a network.
"""

import asyncio
import base64
import json

import pytest

from src.api.voice import protocol as p
from src.api.voice.bridge import (
    VoiceUpstreamError,
    build_setup_frame,
    encode_audio_chunk,
    run_bridge,
)
from src.api.voice.config import LiveVoiceConfig

CONFIG = LiveVoiceConfig(
    provider_id="gemini",
    protocol="bidi_generate_content_v1beta",
    ws_url="wss://upstream.test/ws",
    auth_query_param="key",
    model="gemini-3.1-flash-live-preview",
    model_prefix="models/",
    input_sample_rate=16000,
    input_mime_type="audio/pcm;rate=16000",
    output_sample_rate=24000,
    max_session_seconds=300,
    voices=("Puck",),
)

SECRET_KEY = "super-secret-provider-key"


class FakeUpstream:
    """Stands in for the provider's WebSocket.

    After the scripted frames are exhausted the iterator *blocks* rather than
    ending, because a real upstream socket stays open. Ending it would let the
    downward pump win the race and mask whatever the client-side pump did.
    """

    def __init__(self, script, *, first=None):
        self.script = list(script)
        self.first = first if first is not None else {"setupComplete": {}}
        self.sent = []
        self.connected_url = None
        self.closed = False
        # Set once the script is drained, so the client stub can sequence its
        # terminal frame after every upstream frame has been handled.
        self.drained = asyncio.Event()
        if not self.script:
            self.drained.set()

    def __call__(self, url, **_kwargs):
        self.connected_url = url
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        self.closed = True
        return False

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        return json.dumps(self.first)

    def __aiter__(self):
        async def gen():
            for frame in self.script:
                yield json.dumps(frame)
            self.drained.set()
            # Stay open; the pump that ends the session is the other one.
            await asyncio.Event().wait()

        return gen()


class FakeClient:
    """Stands in for the browser side of the socket."""

    def __init__(self, inbound, *, after=None):
        self._inbound = list(inbound)
        # Awaited before the terminal frame, so upstream frames are all handled
        # before the client hangs up.
        self._after = after
        self.binary = []
        self.json = []

    async def receive(self):
        if self._inbound:
            return self._inbound.pop(0)
        if self._after is not None:
            await self._after.wait()
            # Yield once so the downward pump can drain its queue.
            await asyncio.sleep(0)
        return {"type": "websocket.disconnect"}

    async def send_bytes(self, data):
        self.binary.append(data)

    async def send_json(self, payload):
        self.json.append(payload)

    def frames_of(self, kind):
        return [f for f in self.json if f.get("t") == kind]


def audio_frame(pcm: bytes) -> dict:
    return {
        "serverContent": {
            "modelTurn": {
                "parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000",
                                          "data": base64.b64encode(pcm).decode()}}]
            }
        }
    }


async def drive(upstream, client, monkeypatch, **kwargs):
    monkeypatch.setattr("src.api.voice.bridge.websockets.connect", upstream)
    return await run_bridge(
        config=CONFIG,
        api_key=SECRET_KEY,
        system_instruction="You are a test assistant.",
        client_receive=client.receive,
        client_send_bytes=client.send_bytes,
        client_send_json=client.send_json,
        **kwargs,
    )


class TestSetupFrame:
    def test_carries_prefixed_model_and_audio_modality(self):
        frame = build_setup_frame(CONFIG, system_instruction="P")["setup"]
        assert frame["model"] == "models/gemini-3.1-flash-live-preview"
        assert frame["generationConfig"]["responseModalities"] == ["AUDIO"]
        assert frame["systemInstruction"]["parts"][0]["text"] == "P"

    def test_requests_transcripts(self):
        # Transcripts are what let a spoken turn land in the message history.
        frame = build_setup_frame(CONFIG, system_instruction="P")["setup"]
        assert "inputAudioTranscription" in frame
        assert "outputAudioTranscription" in frame

    def test_voice_name_is_optional(self):
        assert "speechConfig" not in build_setup_frame(CONFIG, system_instruction="P")["setup"]["generationConfig"]
        with_voice = build_setup_frame(CONFIG, system_instruction="P", voice_name="Kore")
        assert (
            with_voice["setup"]["generationConfig"]["speechConfig"]["voiceConfig"]
            ["prebuiltVoiceConfig"]["voiceName"] == "Kore"
        )

    def test_audio_chunk_is_base64_with_declared_mime(self):
        encoded = encode_audio_chunk(CONFIG, b"\x01\x02")["realtimeInput"]["audio"]
        assert encoded["mimeType"] == "audio/pcm;rate=16000"
        assert base64.b64decode(encoded["data"]) == b"\x01\x02"


class TestKeyHandling:
    @pytest.mark.asyncio
    async def test_key_goes_upstream_only(self, monkeypatch):
        upstream = FakeUpstream([{"serverContent": {"turnComplete": True}}])
        client = FakeClient([{"type": "websocket.receive", "text": json.dumps({"t": "bye"})}])
        await drive(upstream, client, monkeypatch)

        assert SECRET_KEY in upstream.connected_url
        # The one thing that must never happen: the provider key reaching the
        # browser, in any frame, in any form.
        serialised = json.dumps(client.json) + repr(client.binary)
        assert SECRET_KEY not in serialised
        assert "upstream.test" not in serialised


class TestRelay:
    @pytest.mark.asyncio
    async def test_ready_announces_sample_rates(self, monkeypatch):
        upstream = FakeUpstream([])
        client = FakeClient([{"type": "websocket.receive", "text": json.dumps({"t": "bye"})}])
        await drive(upstream, client, monkeypatch)
        ready = client.frames_of(p.SERVER_READY)
        assert ready and ready[0]["in_rate"] == 16000 and ready[0]["out_rate"] == 24000

    @pytest.mark.asyncio
    async def test_client_audio_is_forwarded(self, monkeypatch):
        upstream = FakeUpstream([])
        client = FakeClient([
            {"type": "websocket.receive", "bytes": b"\x10\x20\x30\x40"},
            {"type": "websocket.receive", "text": json.dumps({"t": "bye"})},
        ])
        stats = await drive(upstream, client, monkeypatch)
        chunks = [f for f in upstream.sent if "realtimeInput" in f and "audio" in f["realtimeInput"]]
        assert len(chunks) == 1
        assert base64.b64decode(chunks[0]["realtimeInput"]["audio"]["data"]) == b"\x10\x20\x30\x40"
        assert stats.bytes_in == 4

    @pytest.mark.asyncio
    async def test_stop_sends_audio_stream_end(self, monkeypatch):
        upstream = FakeUpstream([])
        client = FakeClient([
            {"type": "websocket.receive", "text": json.dumps({"t": "stop"})},
            {"type": "websocket.receive", "text": json.dumps({"t": "bye"})},
        ])
        await drive(upstream, client, monkeypatch)
        assert {"realtimeInput": {"audioStreamEnd": True}} in upstream.sent

    @pytest.mark.asyncio
    async def test_model_audio_arrives_as_binary(self, monkeypatch):
        upstream = FakeUpstream([audio_frame(b"\xaa\xbb")])
        client = FakeClient([], after=upstream.drained)
        stats = await drive(upstream, client, monkeypatch)
        assert client.binary == [b"\xaa\xbb"]
        assert stats.bytes_out == 2

    @pytest.mark.asyncio
    async def test_transcripts_are_relayed_and_collected(self, monkeypatch):
        upstream = FakeUpstream([
            {"serverContent": {"inputTranscription": {"text": "hello there"}}},
            {"serverContent": {"outputTranscription": {"text": "hi back"}}},
            {"serverContent": {"turnComplete": True}},
        ])
        client = FakeClient([], after=upstream.drained)
        stats = await drive(upstream, client, monkeypatch)
        assert client.frames_of(p.SERVER_USER_TEXT)[0]["d"] == "hello there"
        assert client.frames_of(p.SERVER_AGENT_TEXT)[0]["d"] == "hi back"
        assert stats.user_text == ["hello there"]
        assert stats.agent_text == ["hi back"]
        assert stats.turns == 1

    @pytest.mark.asyncio
    async def test_interruption_is_relayed(self, monkeypatch):
        # Barge-in has to reach the browser promptly or the model talks over the
        # user for as long as audio stays queued.
        upstream = FakeUpstream([{"serverContent": {"interrupted": True}}])
        client = FakeClient([], after=upstream.drained)
        await drive(upstream, client, monkeypatch)
        assert client.frames_of(p.SERVER_INTERRUPTED)

    @pytest.mark.asyncio
    async def test_go_away_ends_with_upstream_reason(self, monkeypatch):
        upstream = FakeUpstream([{"goAway": {"timeLeft": "1s"}}])
        client = FakeClient([])
        stats = await drive(upstream, client, monkeypatch)
        assert stats.reason == p.REASON_UPSTREAM


class TestLimits:
    @pytest.mark.asyncio
    async def test_oversized_audio_frame_is_dropped(self, monkeypatch):
        upstream = FakeUpstream([])
        client = FakeClient([
            {"type": "websocket.receive", "bytes": b"\x00" * (64 * 1024 + 1)},
            {"type": "websocket.receive", "text": json.dumps({"t": "bye"})},
        ])
        stats = await drive(upstream, client, monkeypatch)
        assert not [f for f in upstream.sent if "realtimeInput" in f and "audio" in f["realtimeInput"]]
        assert stats.bytes_in == 0

    @pytest.mark.asyncio
    async def test_byte_budget_ends_the_session(self, monkeypatch):
        # The real defence against a client streaming audio far faster than
        # realtime to run up a bill.
        tiny = LiveVoiceConfig(**{**CONFIG.__dict__, "max_session_seconds": 1})
        upstream = FakeUpstream([])
        # 1s * 16000 * 2 * 1.5 = 48000 byte budget.
        client = FakeClient([
            {"type": "websocket.receive", "bytes": b"\x00" * 32000},
            {"type": "websocket.receive", "bytes": b"\x00" * 32000},
            {"type": "websocket.receive", "text": json.dumps({"t": "bye"})},
        ])
        monkeypatch.setattr("src.api.voice.bridge.websockets.connect", upstream)
        stats = await run_bridge(
            config=tiny,
            api_key=SECRET_KEY,
            system_instruction="P",
            client_receive=client.receive,
            client_send_bytes=client.send_bytes,
            client_send_json=client.send_json,
        )
        assert stats.reason == p.REASON_BYTE_LIMIT


class TestUpstreamFailures:
    @pytest.mark.asyncio
    async def test_missing_setup_complete_raises(self, monkeypatch):
        upstream = FakeUpstream([], first={"error": {"message": "bad model"}})
        client = FakeClient([])
        with pytest.raises(VoiceUpstreamError, match="unexpected first upstream frame"):
            await drive(upstream, client, monkeypatch)

    @pytest.mark.asyncio
    async def test_client_disconnect_ends_cleanly(self, monkeypatch):
        upstream = FakeUpstream([])
        client = FakeClient([{"type": "websocket.disconnect"}])
        stats = await drive(upstream, client, monkeypatch)
        assert stats.reason == p.REASON_CLIENT
        assert upstream.closed
