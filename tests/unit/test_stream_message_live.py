"""Tests for live SSE streaming through SessionManager.stream_message."""

import asyncio
import threading
from typing import Any

import pytest

from src.core.events import ResponseDeltaType
from src.crewai_runtime.runtime import CrewAIRuntimeResult


class FakeRuntime:
    """Emits node events from a worker thread, like the real kickoff path."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.received_sink = None

    async def run_message(
        self,
        workflow: Any,
        message: str,
        session_id: str,
        user_id: str,
        metadata: dict[str, Any] | None = None,
        event_sink: Any = None,
    ) -> CrewAIRuntimeResult:
        self.received_sink = event_sink
        if self.fail:
            raise RuntimeError("kickoff exploded")

        def worker() -> None:
            event_sink("node_started", {"node_id": "n1"}, "a1")
            event_sink("node_input", {"node_id": "n1", "input": {"message": message}}, "a1")
            event_sink("node_output", {"node_id": "n1", "output": {"raw": "result"}}, "a1")

        thread = threading.Thread(target=worker)
        thread.start()
        while thread.is_alive():
            await asyncio.sleep(0.01)
        return CrewAIRuntimeResult(
            response="final answer",
            trace_steps=[],
            metadata={"runtime": "crewai", "node_io": {"n1": {"output": {"raw": "result"}}}},
        )


@pytest.fixture
def session_manager(monkeypatch, tmp_path):
    class FakeAppSettings:
        crewai_memory_enabled = False
        crewai_storage_dir = str(tmp_path)
        crewai_process_default = "sequential"
        max_concurrent_runs_per_workflow = 10

    class FakeSettings:
        app = FakeAppSettings()

    class FakeWorkflowRegistry:
        def get_workflow(self, workflow_id: str):
            return object() if workflow_id == "wf1" else None

    monkeypatch.setattr("src.api.session_manager.get_settings", lambda: FakeSettings())
    monkeypatch.setattr(
        "src.api.session_manager.get_workflow_registry", lambda: FakeWorkflowRegistry()
    )

    from src.api.session_manager import SessionManager

    return SessionManager(runtime=FakeRuntime())


async def test_stream_message_yields_live_node_events(session_manager) -> None:
    session = await session_manager.create_session("wf1")
    deltas = [delta async for delta in session_manager.stream_message(session.session_id, "hello")]

    types = [delta.type for delta in deltas]
    assert types[0] == ResponseDeltaType.START
    assert types[-1] == ResponseDeltaType.DONE
    assert ResponseDeltaType.NODE_STARTED in types
    assert ResponseDeltaType.NODE_INPUT in types
    assert ResponseDeltaType.NODE_OUTPUT in types
    # node events arrive before the final response frames
    assert types.index(ResponseDeltaType.NODE_OUTPUT) < types.index(ResponseDeltaType.TOKEN)

    sequences = [delta.sequence for delta in deltas]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)

    token = next(d for d in deltas if d.type == ResponseDeltaType.TOKEN)
    assert token.payload == {"text": "final answer"}
    node_output = next(d for d in deltas if d.type == ResponseDeltaType.NODE_OUTPUT)
    assert node_output.payload["node_id"] == "n1"
    assert node_output.agent_id == "a1"
    done = next(d for d in deltas if d.type == ResponseDeltaType.DONE)
    assert done.payload["metadata"]["node_io"]["n1"]["output"]["raw"] == "result"


async def test_stream_message_passes_event_sink_to_runtime(session_manager) -> None:
    session = await session_manager.create_session("wf1")
    async for _ in session_manager.stream_message(session.session_id, "hello"):
        pass
    assert session_manager.runtime.received_sink is not None


async def test_stream_message_emits_error_when_run_fails(monkeypatch, session_manager) -> None:
    session_manager.runtime = FakeRuntime(fail=True)
    session = await session_manager.create_session("wf1")
    deltas = [delta async for delta in session_manager.stream_message(session.session_id, "hello")]
    types = [delta.type for delta in deltas]
    assert types[0] == ResponseDeltaType.START
    assert types[-1] == ResponseDeltaType.ERROR
    assert ResponseDeltaType.DONE not in types
    error = deltas[-1]
    assert error.payload["error_message"] == "kickoff exploded"
