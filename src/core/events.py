"""Typed event models for streaming agent execution."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ResponseDeltaType(StrEnum):
    """Event types emitted by streaming agent execution."""

    START = "start"
    TOKEN = "token"
    REASONING_DELTA = "reasoning_delta"
    NODE_STARTED = "node_started"
    NODE_INPUT = "node_input"
    NODE_OUTPUT = "node_output"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_ARGS = "tool_call_args"
    TOOL_CALL_RESULT = "tool_call_result"
    AGENT_TRANSFER = "agent_transfer"
    CITATION = "citation"
    ERROR = "error"
    DONE = "done"


class ResponseDelta(BaseModel):
    """A single streamable update from an agent run."""

    type: ResponseDeltaType
    session_id: str
    sequence: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)
    agent_id: str | None = None
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    span_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_sse(self) -> str:
        """Serialize the delta as a Server-Sent Events frame."""
        return f"event: {self.type.value}\ndata: {self.model_dump_json()}\n\n"


class StreamEventBuilder:
    """Create ordered deltas for one session stream."""

    def __init__(self, session_id: str, correlation_id: str | None = None) -> None:
        self.session_id = session_id
        self.correlation_id = correlation_id or str(uuid4())
        self._sequence = 0

    def delta(
        self,
        event_type: ResponseDeltaType,
        payload: dict[str, Any] | None = None,
        agent_id: str | None = None,
        span_id: str | None = None,
    ) -> ResponseDelta:
        """Build the next ordered delta."""
        delta = ResponseDelta(
            type=event_type,
            session_id=self.session_id,
            sequence=self._sequence,
            payload=payload or {},
            agent_id=agent_id,
            correlation_id=self.correlation_id,
            span_id=span_id,
        )
        self._sequence += 1
        return delta
