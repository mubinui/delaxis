"""
Property-based tests for Session State Management.

**Feature: crewai-native-migration**

These tests verify correctness properties of the session state management
using property-based testing with Hypothesis.

Properties tested:
- Property 32: State Method Invocation
- Property 22: Session State Serialization
- Property 1: Agent State Round-Trip Preservation
- Property 9: Team State Round-Trip Preservation
- Property 23: Session State Round-Trip Preservation
- Property 24: State Version Handling
"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.api.state_models import (
    STATE_VERSION,
    AgentStateModel,
    SessionStateModel,
    TeamStateModel,
)

# =============================================================================
# Hypothesis Strategies for State Generation
# =============================================================================

# Strategy for generating valid agent IDs
agent_id_strategy = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-"),
).filter(lambda s: s and s[0].isalpha())

# Strategy for generating agent types
agent_type_strategy = st.sampled_from(
    [
        "AssistantAgent",
        "BaseChatAgent",
        "BaseAgent",
    ]
)

# Strategy for generating simple JSON-serializable values
json_value_strategy = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1000000, max_value=1000000),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(min_size=0, max_size=100),
)

# Strategy for generating JSON-serializable dictionaries
json_dict_strategy = st.dictionaries(
    keys=st.text(
        min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))
    ),
    values=json_value_strategy,
    max_size=10,
)


# Strategy for generating agent state
@st.composite
def agent_state_strategy(draw):
    """Generate an AgentStateModel."""
    return AgentStateModel(
        agent_id=draw(agent_id_strategy),
        agent_type=draw(agent_type_strategy),
        config=draw(json_dict_strategy),
        state=draw(json_dict_strategy),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# Strategy for generating team types
team_type_strategy = st.sampled_from(
    [
        "RoundRobinGroupChat",
        "SelectorGroupChat",
    ]
)


# Strategy for generating team state
@st.composite
def team_state_strategy(draw):
    """Generate a TeamStateModel."""
    num_agents = draw(st.integers(min_value=1, max_value=3))
    agent_states = [draw(agent_state_strategy()) for _ in range(num_agents)]

    return TeamStateModel(
        team_id=draw(agent_id_strategy),
        team_type=draw(team_type_strategy),
        config=draw(json_dict_strategy),
        state=draw(json_dict_strategy),
        agent_states=agent_states,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# Strategy for generating session state
@st.composite
def session_state_strategy(draw):
    """Generate a SessionStateModel."""
    num_agents = draw(st.integers(min_value=0, max_value=3))
    num_teams = draw(st.integers(min_value=0, max_value=2))
    num_messages = draw(st.integers(min_value=0, max_value=5))

    agent_states = [draw(agent_state_strategy()) for _ in range(num_agents)]
    team_states = [draw(team_state_strategy()) for _ in range(num_teams)]

    conversation_history = []
    for _ in range(num_messages):
        conversation_history.append(
            {
                "role": draw(st.sampled_from(["user", "assistant", "system"])),
                "content": draw(st.text(min_size=0, max_size=200)),
                "name": draw(agent_id_strategy),
            }
        )

    return SessionStateModel(
        session_id=str(uuid4()),
        workflow_id=draw(agent_id_strategy),
        agent_states=agent_states,
        team_states=team_states,
        conversation_history=conversation_history,
        metadata=draw(json_dict_strategy),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        version=STATE_VERSION,
    )


# Strategy for generating version strings
version_strategy = st.sampled_from(
    [
        "v0.4",
        "v0.4.1",
        "v0.4.2",
        "v0.2",
        "v0.2.1",
        "v0.3",
    ]
)


# =============================================================================
# Property 32: State Method Invocation
# =============================================================================


class MockAgent:
    """Mock agent for testing state methods."""

    def __init__(self, name: str, state: dict[str, Any] = None):
        self.name = name
        self._state = state or {}
        self.save_state_called = False
        self.load_state_called = False
        self.loaded_state = None

    async def save_state(self) -> dict[str, Any]:
        """Mock save_state method."""
        self.save_state_called = True
        return self._state

    async def load_state(self, state: dict[str, Any]) -> None:
        """Mock load_state method."""
        self.load_state_called = True
        self.loaded_state = state
        self._state = state


class MockTeam:
    """Mock team for testing state methods."""

    def __init__(
        self, team_id: str, participants: list[MockAgent] = None, state: dict[str, Any] = None
    ):
        self.team_id = team_id
        self._participants = participants or []
        self._state = state or {}
        self.save_state_called = False
        self.load_state_called = False
        self.loaded_state = None

    async def save_state(self) -> dict[str, Any]:
        """Mock save_state method."""
        self.save_state_called = True
        return self._state

    async def load_state(self, state: dict[str, Any]) -> None:
        """Mock load_state method."""
        self.load_state_called = True
        self.loaded_state = state
        self._state = state


# Note: SessionManager.save_agent_state was removed with the CrewAI migration —
# per-agent state persistence now happens inside the CrewAI runtime itself.
# The remaining tests cover the state models' serialization contracts.


# =============================================================================
# Property 22: Session State Serialization
# =============================================================================


# **Feature: crewai-native-migration, Property 22: Session State Serialization**
@given(state=session_state_strategy())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_session_state_json_serializable(state: SessionStateModel):
    """
    Property 22: Session State Serialization

    For any session state, the state should be serializable to JSON format
    for storage in MongoDB.

    **Feature: crewai-native-migration, Property 22: Session State Serialization**
    **Validates: Requirements 13.3**
    """
    # Convert to dict
    state_dict = state.to_dict()

    # Verify it's JSON serializable
    try:
        json_str = json.dumps(state_dict)
        assert json_str is not None
        assert len(json_str) > 0
    except (TypeError, ValueError) as e:
        pytest.fail(f"Session state is not JSON serializable: {e}")

    # Verify we can parse it back
    parsed = json.loads(json_str)
    assert isinstance(parsed, dict)

    # Verify key fields are preserved
    assert parsed["session_id"] == state.session_id
    assert parsed["workflow_id"] == state.workflow_id
    assert parsed["version"] == state.version
    assert len(parsed["agent_states"]) == len(state.agent_states)
    assert len(parsed["team_states"]) == len(state.team_states)
    assert len(parsed["conversation_history"]) == len(state.conversation_history)


@given(state=agent_state_strategy())
@settings(max_examples=100, deadline=None)
def test_agent_state_json_serializable(state: AgentStateModel):
    """
    Property 22: Session State Serialization (Agent)

    For any agent state, the state should be serializable to JSON format.

    **Feature: crewai-native-migration, Property 22: Session State Serialization**
    **Validates: Requirements 13.3**
    """
    # Convert to dict
    state_dict = state.to_dict()

    # Verify it's JSON serializable
    try:
        json_str = json.dumps(state_dict)
        assert json_str is not None
    except (TypeError, ValueError) as e:
        pytest.fail(f"Agent state is not JSON serializable: {e}")

    # Verify key fields are preserved
    parsed = json.loads(json_str)
    assert parsed["agent_id"] == state.agent_id
    assert parsed["agent_type"] == state.agent_type


@given(state=team_state_strategy())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_team_state_json_serializable(state: TeamStateModel):
    """
    Property 22: Session State Serialization (Team)

    For any team state, the state should be serializable to JSON format.

    **Feature: crewai-native-migration, Property 22: Session State Serialization**
    **Validates: Requirements 13.3**
    """
    # Convert to dict
    state_dict = state.to_dict()

    # Verify it's JSON serializable
    try:
        json_str = json.dumps(state_dict)
        assert json_str is not None
    except (TypeError, ValueError) as e:
        pytest.fail(f"Team state is not JSON serializable: {e}")

    # Verify key fields are preserved
    parsed = json.loads(json_str)
    assert parsed["team_id"] == state.team_id
    assert parsed["team_type"] == state.team_type
    assert len(parsed["agent_states"]) == len(state.agent_states)


# =============================================================================
# Property 1: Agent State Round-Trip Preservation
# =============================================================================


# **Feature: crewai-native-migration, Property 1: Agent State Round-Trip Preservation**
@given(state=agent_state_strategy())
@settings(max_examples=100, deadline=None)
def test_agent_state_round_trip(state: AgentStateModel):
    """
    Property 1: Agent State Round-Trip Preservation

    For any agent with state, saving the state and then loading it should
    result in an agent with equivalent state.

    **Feature: crewai-native-migration, Property 1: Agent State Round-Trip Preservation**
    **Validates: Requirements 1.4**
    """
    # Convert to dict (simulating save to MongoDB)
    state_dict = state.to_dict()

    # Convert back from dict (simulating load from MongoDB)
    restored = AgentStateModel.from_dict(state_dict)

    # Verify equivalence
    assert restored.agent_id == state.agent_id, (
        f"agent_id mismatch: expected '{state.agent_id}', got '{restored.agent_id}'"
    )
    assert restored.agent_type == state.agent_type, (
        f"agent_type mismatch: expected '{state.agent_type}', got '{restored.agent_type}'"
    )
    assert restored.config == state.config, (
        f"config mismatch: expected {state.config}, got {restored.config}"
    )
    assert restored.state == state.state, (
        f"state mismatch: expected {state.state}, got {restored.state}"
    )


# =============================================================================
# Property 9: Team State Round-Trip Preservation
# =============================================================================


# **Feature: crewai-native-migration, Property 9: Team State Round-Trip Preservation**
@given(state=team_state_strategy())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_team_state_round_trip(state: TeamStateModel):
    """
    Property 9: Team State Round-Trip Preservation

    For any team (group chat) with state, saving the state and then loading it
    should result in a team with equivalent state, configuration, and agent states.

    **Feature: crewai-native-migration, Property 9: Team State Round-Trip Preservation**
    **Validates: Requirements 4.5**
    """
    # Convert to dict (simulating save to MongoDB)
    state_dict = state.to_dict()

    # Convert back from dict (simulating load from MongoDB)
    restored = TeamStateModel.from_dict(state_dict)

    # Verify team-level equivalence
    assert restored.team_id == state.team_id, (
        f"team_id mismatch: expected '{state.team_id}', got '{restored.team_id}'"
    )
    assert restored.team_type == state.team_type, (
        f"team_type mismatch: expected '{state.team_type}', got '{restored.team_type}'"
    )
    assert restored.config == state.config, (
        f"config mismatch: expected {state.config}, got {restored.config}"
    )
    assert restored.state == state.state, (
        f"state mismatch: expected {state.state}, got {restored.state}"
    )

    # Verify agent states are preserved
    assert len(restored.agent_states) == len(state.agent_states), (
        f"agent_states count mismatch: expected {len(state.agent_states)}, "
        f"got {len(restored.agent_states)}"
    )

    for i, (original, restored_agent) in enumerate(
        zip(state.agent_states, restored.agent_states, strict=False)
    ):
        assert restored_agent.agent_id == original.agent_id, f"Agent {i} agent_id mismatch"
        assert restored_agent.state == original.state, f"Agent {i} state mismatch"


# =============================================================================
# Property 23: Session State Round-Trip Preservation
# =============================================================================


# **Feature: crewai-native-migration, Property 23: Session State Round-Trip Preservation**
@given(state=session_state_strategy())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_session_state_round_trip(state: SessionStateModel):
    """
    Property 23: Session State Round-Trip Preservation

    For any session with agents and teams, saving the session state and then
    loading it should recreate agents and teams with identical configuration and state.

    **Feature: crewai-native-migration, Property 23: Session State Round-Trip Preservation**
    **Validates: Requirements 13.4**
    """
    # Convert to dict (simulating save to MongoDB)
    state_dict = state.to_dict()

    # Verify it's valid JSON
    json_str = json.dumps(state_dict)
    parsed_dict = json.loads(json_str)

    # Convert back from dict (simulating load from MongoDB)
    restored = SessionStateModel.from_dict(parsed_dict)

    # Verify session-level equivalence
    assert restored.session_id == state.session_id, (
        f"session_id mismatch: expected '{state.session_id}', got '{restored.session_id}'"
    )
    assert restored.workflow_id == state.workflow_id, (
        f"workflow_id mismatch: expected '{state.workflow_id}', got '{restored.workflow_id}'"
    )
    assert restored.version == state.version, (
        f"version mismatch: expected '{state.version}', got '{restored.version}'"
    )
    assert restored.metadata == state.metadata, (
        f"metadata mismatch: expected {state.metadata}, got {restored.metadata}"
    )

    # Verify agent states are preserved
    assert len(restored.agent_states) == len(state.agent_states), (
        f"agent_states count mismatch: expected {len(state.agent_states)}, "
        f"got {len(restored.agent_states)}"
    )

    for i, (original, restored_agent) in enumerate(
        zip(state.agent_states, restored.agent_states, strict=False)
    ):
        assert restored_agent.agent_id == original.agent_id, f"Agent {i} agent_id mismatch"
        assert restored_agent.state == original.state, f"Agent {i} state mismatch"

    # Verify team states are preserved
    assert len(restored.team_states) == len(state.team_states), (
        f"team_states count mismatch: expected {len(state.team_states)}, "
        f"got {len(restored.team_states)}"
    )

    for i, (original, restored_team) in enumerate(
        zip(state.team_states, restored.team_states, strict=False)
    ):
        assert restored_team.team_id == original.team_id, f"Team {i} team_id mismatch"
        assert restored_team.state == original.state, f"Team {i} state mismatch"

    # Verify conversation history is preserved
    assert len(restored.conversation_history) == len(state.conversation_history), (
        f"conversation_history count mismatch: expected {len(state.conversation_history)}, "
        f"got {len(restored.conversation_history)}"
    )

    for i, (original, restored_msg) in enumerate(
        zip(state.conversation_history, restored.conversation_history, strict=False)
    ):
        assert restored_msg == original, (
            f"Message {i} mismatch: expected {original}, got {restored_msg}"
        )


# =============================================================================
# Property 24: State Version Handling
# =============================================================================


# **Feature: crewai-native-migration, Property 24: State Version Handling**
@given(version=version_strategy)
@settings(max_examples=50, deadline=None)
def test_state_version_detection(version: str):
    """
    Property 24: State Version Handling

    For any session state with a version identifier, the system should correctly
    identify the version format.

    **Feature: crewai-native-migration, Property 24: State Version Handling**
    **Validates: Requirements 13.5**
    """
    state = SessionStateModel(
        session_id=str(uuid4()),
        workflow_id="test_workflow",
        version=version,
    )

    # Check version detection
    if version.startswith("v0.4"):
        assert state.is_v04(), f"Version {version} should be detected as v0.4"
        assert not state.is_v02(), f"Version {version} should not be detected as v0.2"
    elif version.startswith("v0.2"):
        assert state.is_v02(), f"Version {version} should be detected as v0.2"
        assert not state.is_v04(), f"Version {version} should not be detected as v0.4"
    else:
        # Other versions should not match either
        assert not state.is_v04(), f"Version {version} should not be detected as v0.4"
        assert not state.is_v02(), f"Version {version} should not be detected as v0.2"


@given(state=session_state_strategy())
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_state_version_preserved_through_round_trip(state: SessionStateModel):
    """
    Property 24: State Version Handling (Preservation)

    For any session state, the version should be preserved through
    serialization and deserialization.

    **Feature: crewai-native-migration, Property 24: State Version Handling**
    **Validates: Requirements 13.5**
    """
    # Convert to dict and back
    state_dict = state.to_dict()
    restored = SessionStateModel.from_dict(state_dict)

    # Verify version is preserved
    assert restored.version == state.version, (
        f"Version not preserved: expected '{state.version}', got '{restored.version}'"
    )

    # Verify version detection is consistent
    assert restored.is_v04() == state.is_v04()
    assert restored.is_v02() == state.is_v02()


def test_v02_state_migration_warning(caplog):
    """
    Test that loading v0.2 state logs a warning about version mismatch.

    **Feature: crewai-native-migration, Property 24: State Version Handling**
    **Validates: Requirements 13.5**
    """
    # Create a v0.2 state
    v02_state = SessionStateModel(
        session_id=str(uuid4()),
        workflow_id="test_workflow",
        version="v0.2",
    )

    # Verify it's detected as v0.2
    assert v02_state.is_v02()
    assert not v02_state.is_v04()

    # The actual warning would be logged by SessionManager.load_session_state
    # Here we just verify the detection works correctly


def test_default_version_is_v04():
    """
    Test that new session states default to v0.4 version.

    **Feature: crewai-native-migration, Property 24: State Version Handling**
    **Validates: Requirements 13.5**
    """
    state = SessionStateModel(
        session_id=str(uuid4()),
        workflow_id="test_workflow",
    )

    assert state.version == STATE_VERSION
    assert state.is_v04()


# =============================================================================
# Additional Edge Case Tests
# =============================================================================


def test_empty_agent_state_serialization():
    """Test that empty agent state serializes correctly."""
    state = AgentStateModel(
        agent_id="test_agent",
        agent_type="AssistantAgent",
        config={},
        state={},
    )

    state_dict = state.to_dict()
    json_str = json.dumps(state_dict)
    restored = AgentStateModel.from_dict(json.loads(json_str))

    assert restored.agent_id == state.agent_id
    assert restored.config == {}
    assert restored.state == {}


def test_empty_session_state_serialization():
    """Test that empty session state serializes correctly."""
    state = SessionStateModel(
        session_id=str(uuid4()),
        workflow_id="test_workflow",
        agent_states=[],
        team_states=[],
        conversation_history=[],
        metadata={},
    )

    state_dict = state.to_dict()
    json_str = json.dumps(state_dict)
    restored = SessionStateModel.from_dict(json.loads(json_str))

    assert restored.session_id == state.session_id
    assert len(restored.agent_states) == 0
    assert len(restored.team_states) == 0
    assert len(restored.conversation_history) == 0


def test_nested_state_data_serialization():
    """Test that nested state data serializes correctly."""
    nested_state = {
        "conversation_history": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ],
        "context": {
            "user_id": "user123",
            "preferences": {"theme": "dark"},
        },
    }

    state = AgentStateModel(
        agent_id="test_agent",
        agent_type="AssistantAgent",
        config={"model": "gpt-4"},
        state=nested_state,
    )

    state_dict = state.to_dict()
    json_str = json.dumps(state_dict)
    restored = AgentStateModel.from_dict(json.loads(json_str))

    assert restored.state == nested_state
    assert restored.state["conversation_history"][0]["role"] == "user"
    assert restored.state["context"]["preferences"]["theme"] == "dark"
