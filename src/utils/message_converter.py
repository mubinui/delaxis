"""Message conversion helpers for Delaxis."""

from __future__ import annotations

from typing import Any


class MessageConverter:
    """Convert platform messages and CrewAI results to API DTOs."""

    @staticmethod
    def message_to_dict(message: Any) -> dict[str, Any]:
        return {
            "role": getattr(getattr(message, "role", None), "value", getattr(message, "role", "assistant")),
            "content": getattr(message, "content", str(message)),
            "timestamp": getattr(getattr(message, "timestamp", None), "isoformat", lambda: None)(),
            "metadata": getattr(message, "metadata", {}),
        }

    @staticmethod
    def extract_text(value: Any) -> str:
        raw = getattr(value, "raw", None)
        return str(raw if raw is not None else value)


MessageConverterCrewAI = MessageConverter
