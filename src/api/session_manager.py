"""CrewAI-native session management for Delaxis."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import structlog

from src.config.settings import get_settings
from src.config.workflow_registry import get_workflow_registry
from src.core.events import ResponseDelta, ResponseDeltaType, StreamEventBuilder
from src.crewai_runtime import CrewAIWorkflowRuntime
from src.crewai_runtime.execution_events import EventSink
from src.infrastructure.database.run_store import RunRecorder, get_run_store
from src.memory.models import ConversationState, MessageRole

logger = structlog.get_logger(__name__)

# Trim the run history to its limit once every this many recorded runs.
_PRUNE_EVERY = 50


def _as_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def _run_source(metadata: dict[str, Any], session_metadata: dict[str, Any]) -> str:
    """Name what started a run, for filtering the run history."""
    if metadata.get("test_case_id"):
        return "test"
    if session_metadata.get("deployment"):
        return "deployment"
    explicit = metadata.get("source") or session_metadata.get("source")
    return str(explicit)[:50] if explicit else "chat"


class SessionManager:
    """Manage CrewAI chat sessions behind the existing REST API."""

    def __init__(self, runtime: CrewAIWorkflowRuntime | None = None) -> None:
        settings = get_settings()
        self.workflow_registry = get_workflow_registry()
        self.runtime = runtime or CrewAIWorkflowRuntime(
            memory_enabled=settings.app.crewai_memory_enabled,
            storage_dir=settings.app.crewai_storage_dir,
            default_process=settings.app.crewai_process_default,
        )
        self.storage_path = Path(settings.app.crewai_storage_dir) / "sessions.json"
        self._sessions: dict[str, ConversationState] = {}
        # Per-workflow admission: at most this many runs of one workflow at a
        # time; the rest wait. The counts back GET /topologies/{id}/status.
        self.max_concurrent_runs = settings.app.max_concurrent_runs_per_workflow
        self._run_slots: dict[str, asyncio.Semaphore] = {}
        self._active_runs: dict[str, int] = {}
        self._waiting_runs: dict[str, int] = {}
        self.run_history_limit = settings.app.run_history_limit
        self._runs_since_prune = 0
        self._load_sessions()
        logger.info(
            "crewai_session_manager_initialized",
            memory_enabled=settings.app.crewai_memory_enabled,
            storage_dir=settings.app.crewai_storage_dir,
            restored_sessions=len(self._sessions),
        )

    async def create_session(
        self,
        workflow_id: str,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationState:
        """Create a session for a CrewAI workflow."""
        workflow = self.workflow_registry.get_workflow(workflow_id)
        if workflow is None:
            raise ValueError(f"Workflow not found: {workflow_id}")

        now = datetime.now(UTC)
        session = ConversationState(
            session_id=uuid4(),
            active=True,
            created_at=now,
            updated_at=now,
            turn_count=0,
            messages=[],
            agent_notes=[],
            metadata={
                "workflow_id": workflow_id,
                "user_id": user_id or "default_user",
                "runtime": "crewai",
                **(metadata or {}),
            },
        )
        self._sessions[str(session.session_id)] = session
        self._save_sessions()
        logger.info(
            "crewai_session_created", session_id=session.session_id, workflow_id=workflow_id
        )
        return session

    async def get_session(self, session_id: UUID) -> ConversationState | None:
        """Return a session by ID."""
        return self._sessions.get(str(session_id))

    async def list_sessions(
        self,
        user_id: str | None = None,
        active_only: bool = True,
    ) -> list[ConversationState]:
        """List sessions from the in-process CrewAI session index."""
        sessions = list(self._sessions.values())
        if user_id:
            sessions = [
                session for session in sessions if session.metadata.get("user_id") == user_id
            ]
        if active_only:
            sessions = [session for session in sessions if session.active]
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    async def delete_session(self, session_id: UUID) -> bool:
        """Delete a session."""
        deleted = self._sessions.pop(str(session_id), None) is not None
        if deleted:
            self._save_sessions()
        return deleted

    async def process_message(
        self,
        session_id: UUID,
        message: str,
        max_turns: int | None = None,
        metadata: dict[str, Any] | None = None,
        event_sink: EventSink | None = None,
    ) -> dict[str, Any]:
        """Process one message with CrewAI and return the legacy response DTO."""
        session = await self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        if not session.active:
            raise ValueError(f"Session is no longer active: {session_id}")

        workflow_id = str(session.metadata.get("workflow_id") or "")
        workflow = self.workflow_registry.get_workflow(workflow_id)
        if workflow is None:
            raise ValueError(f"Workflow not found: {workflow_id}")

        session.add_message(MessageRole.USER, message, runtime="crewai")
        session.increment_turn()

        if max_turns and session.turn_count > max_turns:
            session.active = False
            response = (
                "This session reached the configured turn limit. Start a new session to continue."
            )
            session.add_message(MessageRole.ASSISTANT, response, runtime="crewai", limited=True)
            self._save_sessions()
            return self._response(session, response, {"runtime": "crewai", "limited": True})

        run_metadata = {
            "session_metadata": session.metadata,
            "history": session.conversation_history[-20:],
            **(metadata or {}),
        }
        # Routing comes from the deployment record, never from client-supplied
        # metadata: the deployed page's JS is editable by any visitor.
        run_metadata.pop("model_override", None)
        deployment_ref = session.metadata.get("deployment")
        if deployment_ref:
            from src.api.routers.deployments import deployment_model_override

            override = deployment_model_override(str(deployment_ref))
            if override:
                run_metadata["model_override"] = override
        user_id = session.metadata.get("user_id", "default_user")
        record = await self._start_run_record(
            workflow_id, session_id, user_id, message, metadata or {}, session.metadata
        )
        sink = event_sink
        if record is not None:
            recorder = record[1]

            def sink(event_type: str, payload: dict[str, Any], agent_id: str | None = None) -> None:
                recorder.record(event_type, payload, agent_id)
                if event_sink is not None:
                    event_sink(event_type, payload, agent_id)

        try:
            async with self._run_slot(str(workflow_id)):
                result = await self.runtime.run_message(
                    workflow=workflow,
                    message=message,
                    session_id=str(session_id),
                    user_id=user_id,
                    metadata=run_metadata,
                    event_sink=sink,
                )
        except BaseException as exc:
            if record is not None:
                cancelled = isinstance(exc, asyncio.CancelledError)
                error = "The run was cancelled." if cancelled else str(exc) or type(exc).__name__
                record[1].record(
                    "error", {"error_type": type(exc).__name__, "error_message": error}
                )
                # Synchronous: a cancelled task cannot reliably await again.
                self._finish_run_record(record, status="failed", error=error)
            raise

        response_text = result.response or "I could not generate a response."
        session.add_message(
            MessageRole.ASSISTANT,
            response_text,
            runtime="crewai",
            trace_steps=result.trace_steps,
        )
        session.metadata["last_trace_steps"] = result.trace_steps
        session.metadata["last_run"] = result.metadata
        session.updated_at = datetime.now(UTC)
        self._save_sessions()

        response_metadata = {**result.metadata, "trace_steps": result.trace_steps}
        if record is not None:
            record[1].record("token", {"text": response_text})
            record[1].record(
                "done",
                {
                    "runtime": "crewai",
                    "turn_count": session.turn_count,
                    "metadata": {"runtime": "crewai", **response_metadata},
                },
            )
            await asyncio.to_thread(
                self._finish_run_record,
                record,
                status="succeeded",
                response=response_text,
                run_metadata=result.metadata,
            )
            response_metadata["run_id"] = str(record[0])

        return self._response(session, response_text, response_metadata)

    async def _start_run_record(
        self,
        workflow_id: str,
        session_id: UUID,
        user_id: str,
        message: str,
        metadata: dict[str, Any],
        session_metadata: dict[str, Any],
    ) -> tuple[UUID, RunRecorder] | None:
        """Open a run-history record; None when recording is off or the store fails.

        Run history is a record of the work, not part of it: a database problem
        is logged and the run goes ahead unrecorded.
        """
        if self.run_history_limit <= 0:
            return None
        replay_of = _as_uuid(metadata.get("replay_of"))
        source = "replay" if replay_of else _run_source(metadata, session_metadata)
        try:
            run_id = await asyncio.to_thread(
                get_run_store().start,
                workflow_id=workflow_id,
                message=message,
                session_id=str(session_id),
                user_id=user_id,
                source=source,
                replay_of=replay_of,
                metadata={
                    key: value
                    for key, value in metadata.items()
                    if key in ("source", "replay_of", "test_run_id", "test_case_id")
                },
            )
        except Exception as exc:
            logger.warning("run_history_start_failed", workflow_id=workflow_id, error=str(exc))
            return None
        recorder = RunRecorder()
        recorder.record("start", {"runtime": "crewai", "message": message, "source": source})
        return run_id, recorder

    def _finish_run_record(
        self,
        record: tuple[UUID, RunRecorder],
        *,
        status: str,
        response: str | None = None,
        error: str | None = None,
        run_metadata: dict[str, Any] | None = None,
    ) -> None:
        run_id, recorder = record
        meta = run_metadata or {}
        store = get_run_store()
        try:
            store.finish(
                run_id,
                status=status,
                events=recorder.events,
                response=response,
                error=error,
                agents_called=[str(name) for name in meta.get("agents_called", [])],
                tools_called=[str(name) for name in meta.get("tools_called", [])],
                usage=meta.get("usage") if isinstance(meta.get("usage"), dict) else {},
                cost_usd=meta.get("cost_usd"),
            )
            self._runs_since_prune += 1
            if self._runs_since_prune >= _PRUNE_EVERY:
                self._runs_since_prune = 0
                store.prune(self.run_history_limit)
        except Exception as exc:
            logger.warning("run_history_finish_failed", run_id=str(run_id), error=str(exc))

    @contextlib.asynccontextmanager
    async def _run_slot(self, workflow_id: str) -> AsyncIterator[None]:
        """Hold one of the workflow's run slots for the duration of a run."""
        slot = self._run_slots.setdefault(workflow_id, asyncio.Semaphore(self.max_concurrent_runs))
        self._waiting_runs[workflow_id] = self._waiting_runs.get(workflow_id, 0) + 1
        try:
            await slot.acquire()
        finally:
            self._waiting_runs[workflow_id] -= 1
        self._active_runs[workflow_id] = self._active_runs.get(workflow_id, 0) + 1
        try:
            yield
        finally:
            self._active_runs[workflow_id] -= 1
            slot.release()

    def run_status(self, workflow_id: str) -> dict[str, int]:
        """Runs of a workflow executing now, and runs waiting for a slot."""
        return {
            "active": self._active_runs.get(workflow_id, 0),
            "waiting": self._waiting_runs.get(workflow_id, 0),
            "max_concurrent": self.max_concurrent_runs,
        }

    async def stream_message(
        self,
        session_id: UUID,
        message: str,
        max_turns: int | None = None,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> AsyncIterator[ResponseDelta]:
        """Stream CrewAI execution live through the existing SSE event schema.

        Runtime events (node input/output, tool calls, planning trace) are
        pushed from the kickoff worker thread onto an asyncio queue and
        yielded as they happen, while the run itself progresses concurrently.
        The frame contract is unchanged: START first, then live events, then
        the final TOKEN and DONE (ERROR replaces them on failure).
        """
        builder = StreamEventBuilder(str(session_id), correlation_id=correlation_id)
        yield builder.delta(
            ResponseDeltaType.START,
            {"runtime": "crewai", "message_length": len(message), "metadata": metadata or {}},
        )

        queue: asyncio.Queue[tuple[str, dict[str, Any], str | None]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def sink(event_type: str, payload: dict[str, Any], agent_id: str | None = None) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, (event_type, payload, agent_id))
            except RuntimeError:
                # Event loop closed (client disconnected mid-run); the run
                # itself keeps going, we just stop forwarding events.
                pass

        def _build_delta(
            event_type: str, payload: dict[str, Any], agent_id: str | None
        ) -> ResponseDelta:
            try:
                delta_type = ResponseDeltaType(event_type)
            except ValueError:
                delta_type = ResponseDeltaType.REASONING_DELTA
            return builder.delta(delta_type, payload, agent_id=agent_id)

        run_task = asyncio.create_task(
            self.process_message(
                session_id, message, max_turns=max_turns, metadata=metadata, event_sink=sink
            )
        )
        # Retrieve the exception even if the client disconnects before we await
        # the task, so a failed run never surfaces as "exception never retrieved".
        run_task.add_done_callback(self._log_stream_run_failure)

        pending_get: asyncio.Task[tuple[str, dict[str, Any], str | None]] | None = None
        try:
            while True:
                pending_get = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {pending_get, run_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if pending_get in done:
                    event_type, payload, agent_id = pending_get.result()
                    pending_get = None
                    yield _build_delta(event_type, payload, agent_id)
                    continue
                pending_get.cancel()
                pending_get = None
                break
            while not queue.empty():
                event_type, payload, agent_id = queue.get_nowait()
                yield _build_delta(event_type, payload, agent_id)

            result = await run_task
            response = result.get("response", "")
            if response:
                yield builder.delta(ResponseDeltaType.TOKEN, {"text": response})
            yield builder.delta(
                ResponseDeltaType.DONE,
                {
                    "runtime": "crewai",
                    "turn_count": result.get("turn_count", 0),
                    "metadata": result.get("metadata", {}),
                },
            )
        except Exception as exc:
            logger.error(
                "crewai_message_stream_failed", session_id=session_id, error=str(exc), exc_info=True
            )
            yield builder.delta(
                ResponseDeltaType.ERROR,
                {"error_type": type(exc).__name__, "error_message": str(exc), "runtime": "crewai"},
            )
        finally:
            if pending_get is not None:
                pending_get.cancel()

    @staticmethod
    def _log_stream_run_failure(task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("crewai_stream_run_failed", error=str(exc))

    async def get_chat_history(self, session_id: UUID) -> dict[str, Any]:
        """Return chat history in the router's response shape."""
        session = await self.get_session(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
        return {
            "session_id": session.session_id,
            "messages": [
                {
                    "role": message.role.value,
                    "content": message.content,
                    "timestamp": message.timestamp,
                    "metadata": message.metadata,
                }
                for message in session.messages
            ],
            "agent_notes": [
                {
                    "agent_type": note.agent_type.value,
                    "note_type": note.note_type,
                    "content": note.content,
                    "timestamp": note.timestamp,
                    "metadata": note.metadata,
                }
                for note in session.agent_notes
            ],
            "turn_count": session.turn_count,
            "active": session.active,
            "metadata": session.metadata,
        }

    async def record_voice_turn(
        self,
        session_id: UUID,
        *,
        user_text: str,
        agent_text: str,
        **metadata: Any,
    ) -> bool:
        """Persist one spoken exchange into the session's message history.

        Voice turns go through the same ``add_message`` path as typed ones, so a
        conversation held out loud shows up in ``get_chat_history`` — and
        therefore in the deployed page's transcript on reload — with no separate
        voice log and no schema change. The ``modality`` marker in the message
        metadata is what distinguishes them.

        One write per completed turn rather than per transcript delta; the
        deltas arrive several times a second.
        """
        user_text = (user_text or "").strip()
        agent_text = (agent_text or "").strip()
        if not user_text and not agent_text:
            # Voice activity detection fires on background noise; an empty turn
            # is not worth a row.
            return False

        session = await self.get_session(session_id)
        if session is None:
            return False

        common = {"modality": "voice", **metadata}
        if user_text:
            session.add_message(MessageRole.USER, user_text, **common)
        if agent_text:
            session.add_message(MessageRole.ASSISTANT, agent_text, **common)
        session.increment_turn()
        self._save_sessions()
        return True

    def _response(
        self,
        session: ConversationState,
        response: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta = metadata or {}
        cost_info = {
            "cost_usd": meta.get("cost_usd", 0.0),
            "usage": meta.get("usage", {}),
        }
        return {
            "session_id": session.session_id,
            "response": response,
            "turn_count": session.turn_count,
            "chat_history": session.conversation_history,
            "summary": "",
            "safety_passed": True,
            "cost": cost_info,
            "metadata": {"runtime": "crewai", **meta},
        }

    def _load_sessions(self) -> None:
        """Restore persisted CrewAI sessions from local storage."""
        if not self.storage_path.exists():
            return
        try:
            payload = json.loads(self.storage_path.read_text())
            sessions = payload.get("sessions", payload if isinstance(payload, list) else [])
            for item in sessions:
                session = ConversationState.model_validate(item)
                self._sessions[str(session.session_id)] = session
        except Exception as exc:
            logger.warning(
                "crewai_session_restore_failed", path=str(self.storage_path), error=str(exc)
            )

    def _save_sessions(self) -> None:
        """Persist sessions so run history survives API restarts."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "runtime": "crewai",
                "updated_at": datetime.now(UTC).isoformat(),
                "sessions": [
                    session.model_dump(mode="json")
                    for session in sorted(self._sessions.values(), key=lambda item: item.updated_at)
                ],
            }
            self.storage_path.write_text(json.dumps(payload, indent=2))
        except Exception as exc:
            logger.warning(
                "crewai_session_persist_failed", path=str(self.storage_path), error=str(exc)
            )


_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """Return the process-wide CrewAI session manager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


def reset_session_manager() -> None:
    """Reset the global session manager for tests."""
    global _session_manager
    _session_manager = None
