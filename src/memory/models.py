"""Conversation memory models and data structures."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MessageRole(StrEnum):
    """Role of the message sender."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    AGENT = "agent"


class AgentType(StrEnum):
    """Types of agents in the system."""

    ORCHESTRATOR = "orchestrator"
    REASONING = "reasoning"
    KNOWLEDGE = "knowledge"
    RESPONSE = "response"


class Message(BaseModel):
    """A single message in the conversation."""

    id: UUID = Field(default_factory=uuid4)
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentNote(BaseModel):
    """Annotation or decision recorded by an agent."""

    id: UUID = Field(default_factory=uuid4)
    agent_type: AgentType
    note_type: str  # e.g., "intent", "plan", "knowledge", "safety_check"
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationState(BaseModel):
    """Current state of a conversation session."""

    session_id: UUID = Field(default_factory=uuid4)
    messages: list[Message] = Field(default_factory=list)
    agent_notes: list[AgentNote] = Field(default_factory=list)
    turn_count: int = 0
    active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    def add_message(self, role: MessageRole, content: str, **metadata: Any) -> Message:
        """Add a message to the conversation."""
        message = Message(role=role, content=content, metadata=metadata)
        self.messages.append(message)
        self.updated_at = datetime.now(UTC)
        return message

    def add_agent_note(
        self, agent_type: AgentType, note_type: str, content: str, **metadata: Any
    ) -> AgentNote:
        """Add an agent note to the conversation."""
        note = AgentNote(
            agent_type=agent_type, note_type=note_type, content=content, metadata=metadata
        )
        self.agent_notes.append(note)
        self.updated_at = datetime.now(UTC)
        return note

    def increment_turn(self) -> None:
        """Increment the turn counter."""
        self.turn_count += 1
        self.updated_at = datetime.now(UTC)

    def get_messages_by_role(self, role: MessageRole) -> list[Message]:
        """Get all messages from a specific role."""
        return [msg for msg in self.messages if msg.role == role]

    def get_notes_by_agent(self, agent_type: AgentType) -> list[AgentNote]:
        """Get all notes from a specific agent."""
        return [note for note in self.agent_notes if note.agent_type == agent_type]

    @property
    def conversation_history(self) -> list[dict[str, Any]]:
        """Get conversation history in dict format for ExecutionContext compatibility.

        Returns messages as list of dicts with role, content, and timestamp.
        This property provides backward compatibility with code expecting dict format.
        """
        return [
            {
                "role": msg.role.value,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
            }
            for msg in self.messages
        ]
