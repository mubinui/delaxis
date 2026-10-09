"""Run history: every workflow execution, with the events it streamed.

``RunRecorder`` collects one run's frames while it executes. Runtime events
arrive from the CrewAI worker thread, so it takes a lock. ``RunStore`` writes
the finished record to the SQL database. Its methods are synchronous; async
callers run them with ``asyncio.to_thread``.

The stored frames have the shape the streaming endpoint sends
(``type``, ``payload``, ``agent_id``, ``sequence``, ``timestamp``), with the
``start``, ``token`` and ``done`` (or ``error``) frames added. A recorded run is
therefore a complete stream that the Studio can play back unchanged.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import delete, func, select, update

from src.infrastructure.database.connection import get_db_manager
from src.infrastructure.database.schema import WorkflowRun
from src.utils.time import as_utc, utc_now, utc_now_naive

logger = structlog.get_logger(__name__)

# A run's event log is bounded so one runaway agent loop cannot fill the database.
MAX_EVENTS = 500
MAX_TEXT = 4000
_MAX_DEPTH = 6

RUN_STATUSES = ("running", "succeeded", "failed")


def _bounded(value: Any, depth: int = 0) -> Any:
    """Return ``value`` as JSON-safe data with long strings and deep nesting cut."""
    if isinstance(value, str):
        if len(value) > MAX_TEXT:
            return value[:MAX_TEXT] + f"… [{len(value) - MAX_TEXT} more characters]"
        return value
    if value is None or isinstance(value, bool | int | float):
        return value
    if depth >= _MAX_DEPTH:
        return _bounded(repr(value), depth)
    if isinstance(value, dict):
        return {str(key): _bounded(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_bounded(item, depth + 1) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return _bounded(str(value), depth)


class RunRecorder:
    """The frames of one run, collected as they happen."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self.dropped = 0

    def record(
        self, event_type: str, payload: dict[str, Any] | None = None, agent_id: str | None = None
    ) -> None:
        with self._lock:
            if len(self._events) >= MAX_EVENTS:
                self.dropped += 1
                return
            self._events.append(
                {
                    "type": event_type,
                    "payload": _bounded(payload or {}),
                    "agent_id": agent_id,
                    "sequence": len(self._events),
                    "timestamp": utc_now().isoformat(),
                }
            )

    @property
    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)


def _iso(value: datetime | None) -> str | None:
    aware = as_utc(value)
    return aware.isoformat() if aware else None


def _summary(row: WorkflowRun) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "workflow_id": row.workflow_id,
        "session_id": row.session_id,
        "user_id": row.user_id,
        "source": row.source,
        "status": row.status,
        "message": row.message,
        "response": row.response,
        "error": row.error,
        "agents_called": list(row.agents_called or []),
        "tools_called": list(row.tools_called or []),
        "usage": dict(row.usage or {}),
        "cost_usd": row.cost_usd,
        "replay_of": str(row.replay_of) if row.replay_of else None,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "duration_ms": row.duration_ms,
        "event_count": len(row.events or []),
        "metadata": dict(row.meta_data or {}),
    }


class RunStore:
    """Reads and writes run records on the SQL database."""

    def __init__(self) -> None:
        self._db = get_db_manager()

    def start(
        self,
        *,
        workflow_id: str,
        message: str,
        session_id: str | None = None,
        user_id: str | None = None,
        source: str = "chat",
        replay_of: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UUID:
        """Record that a run has started, and return its id."""
        with self._db.get_session() as session:
            row = WorkflowRun(
                workflow_id=workflow_id,
                session_id=session_id,
                user_id=user_id,
                source=source,
                status="running",
                message=message,
                agents_called=[],
                tools_called=[],
                usage={},
                events=[],
                replay_of=replay_of,
                started_at=utc_now_naive(),
                meta_data=_bounded(metadata or {}),
            )
            session.add(row)
            session.flush()
            return row.id

    def finish(
        self,
        run_id: UUID,
        *,
        status: str,
        events: list[dict[str, Any]],
        response: str | None = None,
        error: str | None = None,
        agents_called: list[str] | None = None,
        tools_called: list[str] | None = None,
        usage: dict[str, Any] | None = None,
        cost_usd: float | None = None,
    ) -> None:
        """Store the outcome and the event log of a run."""
        if status not in RUN_STATUSES:
            raise ValueError(f"Unknown run status: {status}")
        with self._db.get_session() as session:
            row = session.get(WorkflowRun, run_id)
            if row is None:
                raise KeyError(f"Run not found: {run_id}")
            finished = utc_now_naive()
            row.status = status
            row.response = response
            row.error = error
            row.agents_called = list(agents_called or [])
            row.tools_called = list(tools_called or [])
            row.usage = _bounded(usage or {})
            row.cost_usd = cost_usd
            row.events = events
            row.finished_at = finished
            row.duration_ms = int((finished - row.started_at).total_seconds() * 1000)

    def get(self, run_id: UUID, *, with_events: bool = True) -> dict[str, Any] | None:
        with self._db.get_session() as session:
            row = session.get(WorkflowRun, run_id)
            if row is None:
                return None
            record = _summary(row)
            if with_events:
                record["events"] = list(row.events or [])
            return record

    def list(
        self,
        *,
        workflow_id: str | None = None,
        status: str | None = None,
        source: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return a page of runs, newest first, and how many runs match in total."""
        filters = []
        if workflow_id:
            filters.append(WorkflowRun.workflow_id == workflow_id)
        if status:
            filters.append(WorkflowRun.status == status)
        if source:
            filters.append(WorkflowRun.source == source)
        if session_id:
            filters.append(WorkflowRun.session_id == session_id)
        with self._db.get_session() as session:
            total = session.scalar(select(func.count()).select_from(WorkflowRun).where(*filters))
            rows = session.scalars(
                select(WorkflowRun)
                .where(*filters)
                .order_by(WorkflowRun.started_at.desc(), WorkflowRun.id)
                .limit(limit)
                .offset(offset)
            ).all()
            return [_summary(row) for row in rows], int(total or 0)

    def delete(self, run_id: UUID) -> bool:
        with self._db.get_session() as session:
            result = session.execute(delete(WorkflowRun).where(WorkflowRun.id == run_id))
            return bool(getattr(result, "rowcount", 0))

    def prune(self, keep: int) -> int:
        """Delete all but the ``keep`` newest runs; return how many were deleted."""
        stale = (
            select(WorkflowRun.id)
            .order_by(WorkflowRun.started_at.desc(), WorkflowRun.id)
            .offset(keep)
        )
        with self._db.get_session() as session:
            result = session.execute(delete(WorkflowRun).where(WorkflowRun.id.in_(stale)))
            return int(getattr(result, "rowcount", 0) or 0)

    def mark_interrupted(self) -> int:
        """Fail the runs a previous process left marked as running.

        Called once at startup: no run of this process exists yet, so a
        ``running`` row belongs to a process that stopped mid-run.
        """
        with self._db.get_session() as session:
            result = session.execute(
                update(WorkflowRun)
                .where(WorkflowRun.status == "running")
                .values(
                    status="failed",
                    error="The server stopped before this run finished.",
                    finished_at=utc_now_naive(),
                )
            )
            return int(getattr(result, "rowcount", 0) or 0)


_run_store: RunStore | None = None


def get_run_store() -> RunStore:
    global _run_store
    if _run_store is None:
        _run_store = RunStore()
    return _run_store


def reset_run_store() -> None:
    global _run_store
    _run_store = None
