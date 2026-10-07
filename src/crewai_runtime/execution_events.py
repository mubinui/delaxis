"""Per-node execution event emission for CrewAI runs.

The runtime executes one CrewAI ``Crew`` per message; CrewAI only exposes the
final result, so per-node visibility comes from ``Crew(task_callback=...)``.
``ExecutionEventEmitter`` owns that callback: it maps each ``TaskOutput`` back
to its topology node (tasks are named after node ids), records every node's
input/output, and pushes typed events through an optional sink so the API
layer can stream them live over SSE.

The emitter must never break a run: every emission is wrapped so sink or
payload failures are swallowed and logged.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Callable(event_type, payload, agent_id) invoked from the kickoff worker thread.
EventSink = Callable[[str, dict[str, Any], str | None], None]

MAX_TEXT_CHARS = 6000


def _truncate(value: Any) -> tuple[Any, bool]:
    """Clamp long text so a single node output cannot bloat the SSE stream."""
    if isinstance(value, str) and len(value) > MAX_TEXT_CHARS:
        return value[:MAX_TEXT_CHARS] + "… [truncated]", True
    return value, False


@dataclass
class TaskMeta:
    """Build-time facts about one CrewAI task / topology node pairing."""

    node_id: str
    agent_id: str | None
    index: int
    description: str
    expected_output: str | None = None
    upstream_node_ids: list[str] = field(default_factory=list)


class ExecutionEventEmitter:
    """Track per-node I/O during one crew kickoff and stream it via a sink.

    Sequential process: task order matches the registered meta order, so the
    next node's ``node_started``/``node_input`` are emitted as soon as the
    previous task completes (its upstream context is fully known by then).
    Hierarchical process: the manager decides ordering, so input and output
    are emitted together when each task completes.
    """

    def __init__(self, sink: EventSink | None, message: str) -> None:
        self._sink = sink
        self._message = message
        self._metas: list[TaskMeta] = []
        self._sequential = True
        self._inputs: dict[str, dict[str, Any]] = {}
        self._outputs: dict[str, dict[str, Any]] = {}
        self._started_at: dict[str, float] = {}
        self._completed = 0
        self._tool_io: dict[str, dict[str, Any]] = {}
        # What actually ran, in order of first activity. The run result reports
        # these, not the configured lists, so "called" never means "available".
        self._agents_ran: list[str] = []
        self._tools_called: list[str] = []
        self._lock = threading.Lock()

    def register_tasks(self, metas: list[TaskMeta], sequential: bool = True) -> None:
        self._metas = list(metas)
        self._sequential = sequential

    def on_kickoff_start(self) -> None:
        """Sequential runs know their first task up front — announce it."""
        with self._lock:
            if self._sequential and self._metas:
                self._record_and_emit_input(self._metas[0])

    def task_callback(self, task_output: Any) -> None:
        """CrewAI invokes this in the worker thread after each task completes."""
        try:
            with self._lock:
                self._handle_task_output(task_output)
        except Exception as exc:  # noqa: BLE001 - UI events must never kill a run
            logger.warning("execution_event_task_callback_failed", error=str(exc))

    def _handle_task_output(self, task_output: Any) -> None:
        name = getattr(task_output, "name", None)
        meta = next((m for m in self._metas if m.node_id == name), None)
        if meta is None and self._completed < len(self._metas):
            meta = self._metas[self._completed]
        self._completed += 1
        if meta is None:
            return
        if meta.agent_id and meta.agent_id not in self._agents_ran:
            self._agents_ran.append(meta.agent_id)

        # Hierarchical runs (or a missed predictive start) learn the input
        # only now that the manager actually dispatched the task.
        if meta.node_id not in self._inputs:
            self._record_and_emit_input(meta)

        raw, truncated = _truncate(getattr(task_output, "raw", None) or str(task_output))
        description, _ = _truncate(getattr(task_output, "description", None))
        output_payload: dict[str, Any] = {
            "raw": raw,
            "agent": getattr(task_output, "agent", None),
            "expected_output": getattr(task_output, "expected_output", None)
            or meta.expected_output,
            "description": description,
        }
        if truncated:
            output_payload["truncated"] = True
        self._outputs[meta.node_id] = output_payload

        duration_ms = None
        started = self._started_at.get(meta.node_id)
        if started is not None:
            duration_ms = round((time.perf_counter() - started) * 1000)
        self._emit(
            "node_output",
            {
                "node_id": meta.node_id,
                "agent_id": meta.agent_id,
                "output": output_payload,
                "duration_ms": duration_ms,
            },
            meta.agent_id,
        )

        if self._sequential:
            next_meta = next(
                (m for m in self._metas if m.node_id not in self._inputs),
                None,
            )
            if next_meta is not None:
                self._record_and_emit_input(next_meta)

    def _record_and_emit_input(self, meta: TaskMeta) -> None:
        context = [
            {"node_id": upstream_id, "output": self._outputs[upstream_id].get("raw")}
            for upstream_id in meta.upstream_node_ids
            if upstream_id in self._outputs
        ]
        description, truncated = _truncate(meta.description)
        message, message_truncated = _truncate(self._message)
        input_payload: dict[str, Any] = {
            "description": description,
            "message": message,
            "context": context,
        }
        if truncated or message_truncated:
            input_payload["truncated"] = True
        self._inputs[meta.node_id] = input_payload
        self._started_at[meta.node_id] = time.perf_counter()

        self._emit(
            "node_started",
            {
                "node_id": meta.node_id,
                "agent_id": meta.agent_id,
                "task_index": meta.index,
                "description_preview": meta.description[:240],
            },
            meta.agent_id,
        )
        self._emit(
            "node_input",
            {"node_id": meta.node_id, "agent_id": meta.agent_id, "input": input_payload},
            meta.agent_id,
        )

    def agent_step(
        self,
        agent_id: str,
        node_id: str | None,
        step: Any,
        *,
        delegated_from: str | None = None,
    ) -> None:
        """Called from each agent's ``step_callback`` in the agent's own thread.

        Records that the agent really executed. In a manager-led (hierarchical)
        crew the specialists have no task of their own, so their first step is
        announced as an ``agent_transfer`` onto their canvas node and their final
        answer as that node's ``node_output``.
        """
        try:
            first = False
            with self._lock:
                if agent_id not in self._agents_ran:
                    self._agents_ran.append(agent_id)
                    first = True
            if delegated_from is None or node_id is None:
                return
            if first:
                started = time.perf_counter()
                with self._lock:
                    self._started_at.setdefault(node_id, started)
                self._emit(
                    "agent_transfer",
                    {
                        "node_id": node_id,
                        "from_node_id": delegated_from,
                        "target_agent": agent_id,
                    },
                    agent_id,
                )
            output = getattr(step, "output", None)
            is_final = output is not None and not hasattr(step, "tool")
            if is_final:
                raw, truncated = _truncate(str(output))
                payload: dict[str, Any] = {"raw": raw, "agent": agent_id}
                if truncated:
                    payload["truncated"] = True
                with self._lock:
                    self._outputs[node_id] = payload
                    started_at = self._started_at.get(node_id)
                duration_ms = (
                    round((time.perf_counter() - started_at) * 1000) if started_at else None
                )
                self._emit(
                    "node_output",
                    {
                        "node_id": node_id,
                        "agent_id": agent_id,
                        "output": payload,
                        "duration_ms": duration_ms,
                    },
                    agent_id,
                )
        except Exception as exc:  # noqa: BLE001 - UI events must never kill a run
            logger.warning("execution_event_agent_step_failed", error=str(exc))

    @property
    def agents_ran(self) -> list[str]:
        """Agent ids that executed at least one step, in order of first step."""
        with self._lock:
            return list(self._agents_ran)

    @property
    def tools_called(self) -> list[str]:
        """Tool ids that were actually invoked, in order of first call."""
        with self._lock:
            return list(self._tools_called)

    def tool_started(self, tool_id: str, name: str, kwargs: dict[str, Any]) -> None:
        args = {key: _truncate(value)[0] for key, value in (kwargs or {}).items()}
        with self._lock:
            self._tool_io[name] = {"name": name, "tool_id": tool_id, "args": args}
            if tool_id not in self._tools_called:
                self._tools_called.append(tool_id)
        self._emit("tool_call_start", {"name": name, "tool_id": tool_id, "args": args}, None)

    def tool_finished(
        self,
        tool_id: str,
        name: str,
        result: Any = None,
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "name": name,
            "tool_id": tool_id,
            "result": _truncate(
                result if isinstance(result, str) else str(result) if result is not None else None
            )[0],
            "duration_ms": duration_ms,
        }
        if error:
            payload["error"] = error
        with self._lock:
            record = self._tool_io.setdefault(name, {"name": name, "tool_id": tool_id})
            record.update({k: v for k, v in payload.items() if k not in {"name", "tool_id"}})
        self._emit("tool_call_result", payload, None)

    def emit_trace(self, step: dict[str, Any]) -> None:
        """Replay a planning-trace step through the live stream."""
        self._emit("reasoning_delta", step, step.get("agent"))

    def node_io(self) -> dict[str, dict[str, Any]]:
        """Per-node input/output snapshot for post-run metadata."""
        return {
            meta.node_id: {
                "input": self._inputs.get(meta.node_id),
                "output": self._outputs.get(meta.node_id),
            }
            for meta in self._metas
            if meta.node_id in self._inputs or meta.node_id in self._outputs
        }

    def tool_io(self) -> dict[str, dict[str, Any]]:
        """Per-tool call snapshot (last call per tool name) for post-run metadata."""
        return dict(self._tool_io)

    def _emit(self, event_type: str, payload: dict[str, Any], agent_id: str | None) -> None:
        if self._sink is None:
            return
        try:
            self._sink(event_type, payload, agent_id)
        except Exception as exc:  # noqa: BLE001 - UI events must never kill a run
            logger.debug("execution_event_sink_failed", event_type=event_type, error=str(exc))
