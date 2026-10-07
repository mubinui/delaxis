"""
State persistence models for CrewAI 0.4 session management.

These models support serialization of agent and team state for MongoDB storage,
enabling session persistence across requests.

Requirements: 1.4, 13.1, 13.2, 13.3, 13.4, 13.5
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

# Current state format version
STATE_VERSION = "v0.4"


class AgentStateModel(BaseModel):
    """
    Serializable agent state for persistence.

    Stores both the agent configuration and its runtime state
    from agent.save_state().
    """

    agent_id: str = Field(description="Unique agent identifier")
    agent_type: str = Field(description="Agent type (assistant, custom, etc.)")
    config: dict[str, Any] = Field(
        default_factory=dict, description="Agent configuration for recreation"
    )
    state: dict[str, Any] = Field(
        default_factory=dict, description="Runtime state from agent.save_state()"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "config": self.config,
            "state": self.state,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentStateModel":
        """Create from dictionary."""
        created_at = data.get("created_at")
        updated_at = data.get("updated_at")

        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)

        return cls(
            agent_id=data.get("agent_id", ""),
            agent_type=data.get("agent_type", ""),
            config=data.get("config", {}),
            state=data.get("state", {}),
            created_at=created_at or datetime.now(UTC),
            updated_at=updated_at or datetime.now(UTC),
        )


class TeamStateModel(BaseModel):
    """
    Serializable team state for persistence.

    Stores team configuration, runtime state from team.save_state(),
    and the states of all agents in the team.
    """

    team_id: str = Field(description="Unique team identifier")
    team_type: str = Field(description="Team type (round_robin, selector, etc.)")
    config: dict[str, Any] = Field(
        default_factory=dict, description="Team configuration for recreation"
    )
    state: dict[str, Any] = Field(
        default_factory=dict, description="Runtime state from team.save_state()"
    )
    agent_states: list[AgentStateModel] = Field(
        default_factory=list, description="States of agents in the team"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "team_id": self.team_id,
            "team_type": self.team_type,
            "config": self.config,
            "state": self.state,
            "agent_states": [a.to_dict() for a in self.agent_states],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TeamStateModel":
        """Create from dictionary."""
        created_at = data.get("created_at")
        updated_at = data.get("updated_at")

        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)

        agent_states = [AgentStateModel.from_dict(a) for a in data.get("agent_states", [])]

        return cls(
            team_id=data.get("team_id", ""),
            team_type=data.get("team_type", ""),
            config=data.get("config", {}),
            state=data.get("state", {}),
            agent_states=agent_states,
            created_at=created_at or datetime.now(UTC),
            updated_at=updated_at or datetime.now(UTC),
        )


class SessionStateModel(BaseModel):
    """
    Complete session state for persistence.

    Contains all information needed to restore a session:
    - Agent states
    - Team states
    - Conversation history
    - Session metadata
    - Version for backward compatibility
    """

    session_id: str = Field(description="Session UUID as string")
    workflow_id: str = Field(description="Workflow identifier")
    agent_states: list[AgentStateModel] = Field(
        default_factory=list, description="States of all agents in the session"
    )
    team_states: list[TeamStateModel] = Field(
        default_factory=list, description="States of all teams in the session"
    )
    conversation_history: list[dict[str, Any]] = Field(
        default_factory=list, description="Serialized conversation messages"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Session metadata")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: str = Field(
        default=STATE_VERSION, description="State format version for compatibility"
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization (MongoDB storage)."""
        return {
            "session_id": self.session_id,
            "workflow_id": self.workflow_id,
            "agent_states": [a.to_dict() for a in self.agent_states],
            "team_states": [t.to_dict() for t in self.team_states],
            "conversation_history": self.conversation_history,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionStateModel":
        """Create from dictionary (MongoDB retrieval)."""
        created_at = data.get("created_at")
        updated_at = data.get("updated_at")

        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)

        agent_states = [AgentStateModel.from_dict(a) for a in data.get("agent_states", [])]
        team_states = [TeamStateModel.from_dict(t) for t in data.get("team_states", [])]

        return cls(
            session_id=data.get("session_id", ""),
            workflow_id=data.get("workflow_id", ""),
            agent_states=agent_states,
            team_states=team_states,
            conversation_history=data.get("conversation_history", []),
            metadata=data.get("metadata", {}),
            created_at=created_at or datetime.now(UTC),
            updated_at=updated_at or datetime.now(UTC),
            version=data.get("version", STATE_VERSION),
        )

    def is_v04(self) -> bool:
        """Check if this state is in v0.4 format."""
        return self.version.startswith("v0.4")

    def is_v02(self) -> bool:
        """Check if this state is in v0.2 format."""
        return self.version.startswith("v0.2")


class StateVersionMismatchError(Exception):
    """Raised when loading state from incompatible version."""

    def __init__(self, expected: str, actual: str, message: str = ""):
        self.expected = expected
        self.actual = actual
        super().__init__(message or f"State version mismatch: expected {expected}, got {actual}")


class StateSerializationError(Exception):
    """Raised when state serialization fails."""

    pass


class StateDeserializationError(Exception):
    """Raised when state deserialization fails."""

    pass
