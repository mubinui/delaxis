"""Tests for per-node execution event emission (ExecutionEventEmitter)."""

from types import SimpleNamespace

from src.crewai_runtime.execution_events import (
    MAX_TEXT_CHARS,
    ExecutionEventEmitter,
    TaskMeta,
)


def make_metas() -> list[TaskMeta]:
    return [
        TaskMeta(node_id="n1", agent_id="a1", index=0, description="first task"),
        TaskMeta(
            node_id="n2",
            agent_id="a2",
            index=1,
            description="second task",
            upstream_node_ids=["n1"],
        ),
    ]


def task_output(name: str, raw: str = "out") -> SimpleNamespace:
    return SimpleNamespace(
        name=name, raw=raw, agent="Role", expected_output="x", description="desc"
    )


def collect() -> tuple[list[tuple[str, dict, str | None]], ExecutionEventEmitter]:
    events: list[tuple[str, dict, str | None]] = []
    emitter = ExecutionEventEmitter(lambda t, p, a: events.append((t, p, a)), "hello")
    return events, emitter


def test_sequential_flow_emits_predictive_input_then_output() -> None:
    events, emitter = collect()
    emitter.register_tasks(make_metas(), sequential=True)

    emitter.on_kickoff_start()
    assert [e[0] for e in events] == ["node_started", "node_input"]
    assert events[0][1]["node_id"] == "n1"

    emitter.task_callback(task_output("n1", raw="alpha"))
    # n1 output, then n2 announced with n1's output as upstream context
    assert [e[0] for e in events] == [
        "node_started",
        "node_input",
        "node_output",
        "node_started",
        "node_input",
    ]
    n1_output = events[2][1]
    assert n1_output["node_id"] == "n1"
    assert n1_output["output"]["raw"] == "alpha"
    assert n1_output["duration_ms"] is not None
    n2_input = events[4][1]
    assert n2_input["node_id"] == "n2"
    assert n2_input["input"]["context"] == [{"node_id": "n1", "output": "alpha"}]
    assert n2_input["input"]["message"] == "hello"

    emitter.task_callback(task_output("n2", raw="beta"))
    assert events[-1][0] == "node_output"
    assert events[-1][1]["node_id"] == "n2"


def test_hierarchical_flow_emits_io_only_at_completion() -> None:
    events, emitter = collect()
    emitter.register_tasks(make_metas(), sequential=False)

    emitter.on_kickoff_start()
    assert events == []  # manager-driven ordering: nothing predictive

    emitter.task_callback(task_output("n2", raw="beta"))
    assert [e[0] for e in events] == ["node_started", "node_input", "node_output"]
    assert all(e[1]["node_id"] == "n2" for e in events)


def test_unknown_task_name_falls_back_to_completion_order() -> None:
    events, emitter = collect()
    emitter.register_tasks(make_metas(), sequential=True)
    emitter.on_kickoff_start()

    emitter.task_callback(task_output(name=None))  # type: ignore[arg-type]
    outputs = [e for e in events if e[0] == "node_output"]
    assert len(outputs) == 1
    assert outputs[0][1]["node_id"] == "n1"


def test_long_text_is_truncated_and_flagged() -> None:
    events, emitter = collect()
    emitter.register_tasks(
        [TaskMeta(node_id="n1", agent_id="a1", index=0, description="d")], sequential=True
    )
    emitter.on_kickoff_start()

    emitter.task_callback(task_output("n1", raw="x" * (MAX_TEXT_CHARS + 500)))
    output_payload = [e for e in events if e[0] == "node_output"][0][1]["output"]
    assert output_payload["truncated"] is True
    assert len(output_payload["raw"]) < MAX_TEXT_CHARS + 50


def test_sink_exceptions_never_propagate() -> None:
    def broken_sink(*_args) -> None:
        raise RuntimeError("boom")

    emitter = ExecutionEventEmitter(broken_sink, "hello")
    emitter.register_tasks(make_metas(), sequential=True)
    emitter.on_kickoff_start()
    emitter.task_callback(task_output("n1"))  # must not raise


def test_node_io_snapshot_collects_inputs_and_outputs() -> None:
    _, emitter = collect()
    emitter.register_tasks(make_metas(), sequential=True)
    emitter.on_kickoff_start()
    emitter.task_callback(task_output("n1", raw="alpha"))
    emitter.task_callback(task_output("n2", raw="beta"))

    io = emitter.node_io()
    assert set(io.keys()) == {"n1", "n2"}
    assert io["n1"]["output"]["raw"] == "alpha"
    assert io["n2"]["input"]["context"][0]["output"] == "alpha"


def test_no_sink_still_records_node_io() -> None:
    emitter = ExecutionEventEmitter(None, "hello")
    emitter.register_tasks(make_metas(), sequential=True)
    emitter.on_kickoff_start()
    emitter.task_callback(task_output("n1", raw="alpha"))
    assert emitter.node_io()["n1"]["output"]["raw"] == "alpha"


def test_tool_io_records_args_and_results_without_sink() -> None:
    emitter = ExecutionEventEmitter(None, "hello")
    emitter.tool_started("gmail_send", "send_email", {"to": "a@b.c", "body": "hi"})
    emitter.tool_finished("gmail_send", "send_email", result="sent", duration_ms=42)
    emitter.tool_started("db_query", "query", {"sql": "select 1"})
    emitter.tool_finished("db_query", "query", error="boom", duration_ms=7)

    tool_io = emitter.tool_io()
    assert tool_io["send_email"]["args"] == {"to": "a@b.c", "body": "hi"}
    assert tool_io["send_email"]["result"] == "sent"
    assert tool_io["send_email"]["duration_ms"] == 42
    assert tool_io["query"]["error"] == "boom"
