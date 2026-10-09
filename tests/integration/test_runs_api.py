"""Run history: every run is recorded with its events, and can be listed, replayed and deleted."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.infrastructure.database.connection import get_db_manager
from src.infrastructure.database.run_store import MAX_EVENTS, MAX_TEXT, RunRecorder, RunStore
from src.infrastructure.database.schema import WorkflowRun

pytestmark = pytest.mark.usefixtures("fixture_workflows", "fake_runtime")


@pytest.fixture(autouse=True)
def empty_history() -> None:
    with get_db_manager().get_session() as session:
        session.query(WorkflowRun).delete()


async def send(client: AsyncClient, workflow_id: str, message: str, **metadata: Any) -> dict:
    created = await client.post(
        "/api/v1/sessions", json={"workflow_id": workflow_id, "user_id": "alice"}
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    reply = await client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"message": message, "metadata": metadata},
    )
    assert reply.status_code == 200, reply.text
    return {"session_id": session_id, **reply.json()}


async def runs(client: AsyncClient, **params: Any) -> dict:
    response = await client.get("/api/v1/runs", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_chat_message_is_recorded_with_its_outcome(async_client: AsyncClient) -> None:
    reply = await send(async_client, "echo_test", "Hello there")
    page = await runs(async_client)
    assert page["total"] == 1
    run = page["items"][0]
    assert run["workflow_id"] == "echo_test"
    assert run["session_id"] == reply["session_id"]
    assert run["user_id"] == "alice"
    assert run["source"] == "chat"
    assert run["status"] == "succeeded"
    assert run["message"] == "Hello there"
    assert run["response"] == "Echo: Hello there"
    assert run["agents_called"] == ["GeneralAssistant"]
    assert run["duration_ms"] >= 0
    assert run["finished_at"] is not None
    assert "events" not in run, "the list leaves the event logs out"
    # The response names the run, so a client can link straight to it.
    assert reply["metadata"]["run_id"] == run["id"]


async def test_a_recorded_run_is_a_complete_stream(async_client: AsyncClient) -> None:
    await send(async_client, "echo_test", "Hi")
    run_id = (await runs(async_client))["items"][0]["id"]
    run = (await async_client.get(f"/api/v1/runs/{run_id}")).json()
    types = [event["type"] for event in run["events"]]
    assert types[0] == "start" and types[-2:] == ["token", "done"]
    assert [event["sequence"] for event in run["events"]] == list(range(len(types)))
    assert run["events"][-2]["payload"] == {"text": "Echo: Hi"}
    assert run["events"][-1]["payload"]["metadata"]["workflow_id"] == "echo_test"
    assert run["event_count"] == len(types)


async def test_streamed_runtime_events_are_recorded_in_order(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.crewai_runtime.runtime import CrewAIRuntimeResult, CrewAIWorkflowRuntime

    async def run_message(self: Any, **kwargs: Any) -> CrewAIRuntimeResult:
        sink = kwargs["event_sink"]
        sink("node_input", {"node_id": "general_assistant", "input": "x"}, "general_assistant")
        sink("tool_call_start", {"name": "calculate", "args": {"expression": "1+1"}}, None)
        sink("node_output", {"node_id": "general_assistant", "output": "2"}, "general_assistant")
        return CrewAIRuntimeResult(
            response="2", trace_steps=[], metadata={"tools_called": ["calculate"]}
        )

    monkeypatch.setattr(CrewAIWorkflowRuntime, "run_message", run_message)
    response = await async_client.post(
        "/api/v1/workflows/echo_test/execute/stream",
        json={"message": "1+1", "metadata": {"source": "canvas_live_run"}},
    )
    frames = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    done = frames[-1]
    assert done["type"] == "done"
    run = (await async_client.get(f"/api/v1/runs/{done['payload']['metadata']['run_id']}")).json()
    assert run["source"] == "canvas_live_run"
    assert run["tools_called"] == ["calculate"]
    assert [event["type"] for event in run["events"]] == [
        "start",
        "node_input",
        "tool_call_start",
        "node_output",
        "token",
        "done",
    ]
    assert run["events"][1]["agent_id"] == "general_assistant"
    # What was recorded is what the live stream sent, apart from the frame bookkeeping.
    live = [(frame["type"], frame["payload"]) for frame in frames[1:-1]]
    recorded = [(event["type"], event["payload"]) for event in run["events"][1:-1]]
    assert live == recorded


async def test_a_failed_run_is_recorded_as_failed(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.crewai_runtime.runtime import CrewAIWorkflowRuntime

    async def run_message(self: Any, **kwargs: Any) -> Any:
        kwargs["event_sink"]("node_input", {"node_id": "general_assistant"}, None)
        raise RuntimeError("provider returned 401")

    monkeypatch.setattr(CrewAIWorkflowRuntime, "run_message", run_message)
    created = await async_client.post("/api/v1/sessions", json={"workflow_id": "echo_test"})
    reply = await async_client.post(
        f"/api/v1/sessions/{created.json()['session_id']}/messages", json={"message": "hi"}
    )
    assert reply.status_code >= 400, "the failure still reaches the caller"
    run = (await runs(async_client, status="failed"))["items"][0]
    assert run["error"] == "provider returned 401"
    assert run["response"] is None
    detail = (await async_client.get(f"/api/v1/runs/{run['id']}")).json()
    assert [event["type"] for event in detail["events"]] == ["start", "node_input", "error"]
    assert detail["events"][-1]["payload"]["error_message"] == "provider returned 401"


async def test_runs_are_filtered_and_paged(async_client: AsyncClient) -> None:
    for text in ("one", "two", "three"):
        await send(async_client, "echo_test", text)
    await send(async_client, "tool_test", "search for cats")
    assert (await runs(async_client))["total"] == 4
    echo = await runs(async_client, workflow_id="echo_test", limit=2)
    assert echo["total"] == 3
    assert [run["message"] for run in echo["items"]] == ["three", "two"], "newest first"
    rest = await runs(async_client, workflow_id="echo_test", limit=2, offset=2)
    assert [run["message"] for run in rest["items"]] == ["one"]
    assert (await runs(async_client, status="failed"))["total"] == 0
    assert (await runs(async_client, source="chat"))["total"] == 4
    bad = await async_client.get("/api/v1/runs", params={"status": "exploded"})
    assert bad.status_code == 400


async def test_the_source_names_what_started_the_run(async_client: AsyncClient) -> None:
    executed = await async_client.post(
        "/api/v1/workflows/echo_test/execute", json={"message": "via execute"}
    )
    assert executed.status_code == 200, executed.text
    created = await async_client.post(
        "/api/v1/workflows/echo_test/test-cases",
        json={"name": "greets", "input_message": "hello", "expected_output_contains": ["hello"]},
    )
    assert created.status_code in (200, 201), created.text
    case_id = created.json()["id"]
    tested = await async_client.post(f"/api/v1/workflows/echo_test/test-cases/{case_id}/run")
    assert tested.status_code == 200, tested.text
    sources = {run["message"]: run["source"] for run in (await runs(async_client))["items"]}
    assert sources == {"via execute": "workflow_execute", "hello": "test"}


async def test_replay_sends_the_recorded_request_again(async_client: AsyncClient) -> None:
    original = await send(async_client, "echo_test", "What is 2+2?")
    original_id = original["metadata"]["run_id"]
    response = await async_client.post(f"/api/v1/runs/{original_id}/replay")
    assert response.status_code == 200, response.text
    replay = response.json()
    assert replay["id"] != original_id
    assert replay["replay_of"] == original_id
    assert replay["source"] == "replay"
    assert replay["status"] == "succeeded"
    assert replay["message"] == "What is 2+2?"
    assert replay["response"] == "Echo: What is 2+2?"
    assert replay["session_id"] != original["session_id"], "a replay gets a fresh session"
    assert replay["events"][0]["type"] == "start"
    assert (await runs(async_client, source="replay"))["total"] == 1


async def test_replay_can_change_the_message(async_client: AsyncClient) -> None:
    original = await send(async_client, "echo_test", "first wording")
    replay = await async_client.post(
        f"/api/v1/runs/{original['metadata']['run_id']}/replay",
        json={"message": "second wording"},
    )
    assert replay.json()["message"] == "second wording"
    assert replay.json()["response"] == "Echo: second wording"


async def test_a_failed_replay_is_returned_as_a_failed_run(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.crewai_runtime.runtime import CrewAIWorkflowRuntime

    original = await send(async_client, "echo_test", "hi")

    async def run_message(self: Any, **kwargs: Any) -> Any:
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(CrewAIWorkflowRuntime, "run_message", run_message)
    replay = await async_client.post(f"/api/v1/runs/{original['metadata']['run_id']}/replay")
    assert replay.status_code == 200
    assert replay.json()["status"] == "failed"
    assert replay.json()["error"] == "model unavailable"


async def test_replaying_a_run_of_a_deleted_workflow_is_a_conflict(
    async_client: AsyncClient,
) -> None:
    run_id = RunStore().start(workflow_id="gone_workflow", message="hi")
    response = await async_client.post(f"/api/v1/runs/{run_id}/replay")
    assert response.status_code == 409
    assert "no longer exists" in response.json()["detail"]


async def test_a_run_can_be_deleted(async_client: AsyncClient) -> None:
    run_id = (await send(async_client, "echo_test", "hi"))["metadata"]["run_id"]
    assert (await async_client.delete(f"/api/v1/runs/{run_id}")).status_code == 204
    assert (await async_client.get(f"/api/v1/runs/{run_id}")).status_code == 404
    assert (await async_client.delete(f"/api/v1/runs/{run_id}")).status_code == 404


async def test_unknown_and_malformed_run_ids(async_client: AsyncClient) -> None:
    assert (await async_client.get(f"/api/v1/runs/{uuid4()}")).status_code == 404
    assert (await async_client.post(f"/api/v1/runs/{uuid4()}/replay")).status_code == 404
    assert (await async_client.get("/api/v1/runs/not-a-uuid")).status_code == 422


async def test_a_broken_history_store_does_not_break_the_run(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("disk full")

    monkeypatch.setattr(RunStore, "start", broken)
    reply = await send(async_client, "echo_test", "still works")
    assert reply["response"] == "Echo: still works"
    assert "run_id" not in reply["metadata"]


async def test_recording_can_be_turned_off(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.api.session_manager import get_session_manager

    monkeypatch.setattr(get_session_manager(), "run_history_limit", 0)
    await send(async_client, "echo_test", "not recorded")
    assert (await runs(async_client))["total"] == 0


async def test_concurrent_runs_are_each_recorded(async_client: AsyncClient) -> None:
    await asyncio.gather(*(send(async_client, "echo_test", f"m{i}") for i in range(8)))
    page = await runs(async_client, limit=20)
    assert sorted(run["message"] for run in page["items"]) == [f"m{i}" for i in range(8)]
    assert {run["status"] for run in page["items"]} == {"succeeded"}


# --- The store itself ------------------------------------------------------------------


def test_prune_keeps_the_newest_runs() -> None:
    store = RunStore()
    ids = [store.start(workflow_id="wf", message=str(i)) for i in range(5)]
    assert store.prune(keep=2) == 3
    remaining, total = store.list()
    assert total == 2
    assert {run["id"] for run in remaining} == {str(ids[3]), str(ids[4])}
    assert store.prune(keep=2) == 0


def test_runs_left_running_by_a_stopped_server_are_marked_failed() -> None:
    store = RunStore()
    run_id = store.start(workflow_id="wf", message="hi")
    assert store.mark_interrupted() == 1
    run = store.get(run_id)
    assert run is not None
    assert run["status"] == "failed"
    assert "stopped" in run["error"]
    assert store.mark_interrupted() == 0


def test_finish_rejects_an_unknown_status() -> None:
    store = RunStore()
    run_id = store.start(workflow_id="wf", message="hi")
    with pytest.raises(ValueError, match="Unknown run status"):
        store.finish(run_id, status="exploded", events=[])


def test_the_event_log_is_bounded() -> None:
    recorder = RunRecorder()
    recorder.record(
        "node_output", {"output": "x" * (MAX_TEXT + 10), "nested": {"a": [1, object()]}}
    )
    first = recorder.events[0]["payload"]
    assert first["output"].endswith("[10 more characters]")
    assert isinstance(first["nested"]["a"][1], str), "unknown objects become text"
    for _ in range(MAX_EVENTS + 5):
        recorder.record("token", {"text": "t"})
    assert len(recorder.events) == MAX_EVENTS
    assert recorder.dropped == 6
