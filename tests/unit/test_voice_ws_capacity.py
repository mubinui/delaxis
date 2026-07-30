"""The voice socket must never leak a concurrency slot.

A realtime session is capped by a process-wide semaphore. accept() used to sit
outside the try/finally that releases it, so a handshake that failed — peer hung
up, proxy dropped it — burned a slot forever. At the default cap of four, four
such failures wedged voice permanently, which is what made it work "sometimes".
"""

import asyncio

import pytest

from src.api.routers import voice as voice_router
from src.api.voice import tickets


class FakeWebSocket:
    """Minimal stand-in; accept() can be told to fail."""

    def __init__(self, *, accept_raises=False):
        self.accept_raises = accept_raises
        self.closed_with = None

    async def accept(self):
        if self.accept_raises:
            raise RuntimeError("peer hung up during handshake")

    async def close(self, code=1000, reason=""):
        self.closed_with = (code, reason)

    async def receive(self):
        return {"type": "websocket.disconnect"}

    async def send_bytes(self, data):
        pass

    async def send_json(self, payload):
        pass


@pytest.fixture(autouse=True)
def fresh_capacity(monkeypatch):
    # Rebuild the module-level semaphore for each test.
    monkeypatch.setattr(voice_router, "_capacity", None)
    monkeypatch.setattr(voice_router, "_capacity_size", 0)
    tickets.reset()
    yield
    tickets.reset()


@pytest.fixture
def working_voice(monkeypatch):
    """Make _resolve_voice_settings succeed without touching a provider."""
    class Config:
        provider_id = "gemini"
        model = "test-live"
        input_sample_rate = 16000
        output_sample_rate = 24000
        max_session_seconds = 5

    monkeypatch.setattr(
        voice_router, "_resolve_voice_settings",
        lambda _dep: (Config(), "test-key", "", "", 5),
    )
    return Config


class TestCapacityRelease:
    @pytest.mark.asyncio
    async def test_slot_is_released_when_accept_fails(self, working_voice, monkeypatch):
        async def never_called(**_kwargs):
            raise AssertionError("the bridge must not open if accept() failed")

        monkeypatch.setattr(voice_router, "run_bridge", never_called)

        before = voice_router._semaphore()._value
        ticket, _ = tickets.mint(session_id="", deployment=None, purpose=tickets.PURPOSE_BUILDER)
        await voice_router.voice_websocket(FakeWebSocket(accept_raises=True), ticket=ticket)

        assert voice_router._semaphore()._value == before, "a failed handshake leaked a slot"

    @pytest.mark.asyncio
    async def test_slot_is_released_on_a_normal_session(self, working_voice, monkeypatch):
        class Stats:
            reason = "client"
            bytes_in = 0
            bytes_out = 0
            turns = 0
            user_text: list[str] = []
            agent_text: list[str] = []

        async def ok_bridge(**_kwargs):
            return Stats()

        monkeypatch.setattr(voice_router, "run_bridge", ok_bridge)

        before = voice_router._semaphore()._value
        ticket, _ = tickets.mint(session_id="", deployment=None, purpose=tickets.PURPOSE_BUILDER)
        await voice_router.voice_websocket(FakeWebSocket(), ticket=ticket)
        assert voice_router._semaphore()._value == before

    @pytest.mark.asyncio
    async def test_slot_is_released_when_the_bridge_raises(self, working_voice, monkeypatch):
        async def boom(**_kwargs):
            raise RuntimeError("upstream exploded")

        monkeypatch.setattr(voice_router, "run_bridge", boom)

        before = voice_router._semaphore()._value
        ticket, _ = tickets.mint(session_id="", deployment=None, purpose=tickets.PURPOSE_BUILDER)
        await voice_router.voice_websocket(FakeWebSocket(), ticket=ticket)
        assert voice_router._semaphore()._value == before

    @pytest.mark.asyncio
    async def test_repeated_failures_do_not_wedge_voice(self, working_voice, monkeypatch):
        """The actual reported symptom: it works, then stops working."""
        async def never_called(**_kwargs):
            raise AssertionError("should not reach the bridge")

        monkeypatch.setattr(voice_router, "run_bridge", never_called)

        cap = voice_router._semaphore()._value
        for _ in range(cap + 2):
            ticket, _ = tickets.mint(session_id="", deployment=None, purpose=tickets.PURPOSE_BUILDER)
            await voice_router.voice_websocket(FakeWebSocket(accept_raises=True), ticket=ticket)

        # Still room for a new caller after more failures than the cap.
        assert voice_router._semaphore()._value == cap
        assert not voice_router._semaphore().locked()
