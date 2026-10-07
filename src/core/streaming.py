"""CrewAI streaming helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from src.core.events import ResponseDelta, ResponseDeltaType, StreamEventBuilder


async def stream_crewai_result(
    builder: StreamEventBuilder,
    result: dict[str, Any],
) -> AsyncIterator[ResponseDelta]:
    """Translate a completed CrewAI result into typed stream events."""
    for step in result.get("metadata", {}).get("trace_steps", []):
        yield builder.delta(ResponseDeltaType.REASONING_DELTA, step)
    if result.get("response"):
        yield builder.delta(ResponseDeltaType.TOKEN, {"text": result["response"]})
    yield builder.delta(
        ResponseDeltaType.DONE, {"runtime": "crewai", "metadata": result.get("metadata", {})}
    )
