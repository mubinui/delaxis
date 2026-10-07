"""Unit tests for conversation memory."""

import pytest

from src.memory import AgentType, ConversationState, InMemoryConversationStore, MessageRole


@pytest.mark.asyncio
async def test_create_session() -> None:
    """Test creating a new conversation session."""
    store = InMemoryConversationStore()
    state = await store.create_session()

    assert state.session_id is not None
    assert state.active is True
    assert state.turn_count == 0
    assert len(state.messages) == 0


@pytest.mark.asyncio
async def test_add_message() -> None:
    """Test adding messages to conversation state."""
    state = ConversationState()

    message = state.add_message(MessageRole.USER, "Hello")
    assert message.role == MessageRole.USER
    assert message.content == "Hello"
    assert len(state.messages) == 1


@pytest.mark.asyncio
async def test_add_agent_note() -> None:
    """Test adding agent notes to conversation state."""
    state = ConversationState()

    note = state.add_agent_note(AgentType.REASONING, "intent", "greeting", confidence=0.9)

    assert note.agent_type == AgentType.REASONING
    assert note.note_type == "intent"
    assert note.content == "greeting"
    assert len(state.agent_notes) == 1


@pytest.mark.asyncio
async def test_increment_turn() -> None:
    """Test incrementing turn counter."""
    state = ConversationState()
    assert state.turn_count == 0

    state.increment_turn()
    assert state.turn_count == 1


@pytest.mark.asyncio
async def test_get_messages_by_role() -> None:
    """Test filtering messages by role."""
    state = ConversationState()
    state.add_message(MessageRole.USER, "Hello")
    state.add_message(MessageRole.ASSISTANT, "Hi there!")
    state.add_message(MessageRole.USER, "How are you?")

    user_messages = state.get_messages_by_role(MessageRole.USER)
    assert len(user_messages) == 2
    assert all(msg.role == MessageRole.USER for msg in user_messages)


@pytest.mark.asyncio
async def test_get_notes_by_agent() -> None:
    """Test filtering notes by agent type."""
    state = ConversationState()
    state.add_agent_note(AgentType.REASONING, "intent", "greeting")
    state.add_agent_note(AgentType.KNOWLEDGE, "fact", "info")
    state.add_agent_note(AgentType.REASONING, "plan", "respond")

    reasoning_notes = state.get_notes_by_agent(AgentType.REASONING)
    assert len(reasoning_notes) == 2
    assert all(note.agent_type == AgentType.REASONING for note in reasoning_notes)


@pytest.mark.asyncio
async def test_store_get_session() -> None:
    """Test retrieving a session from the store."""
    store = InMemoryConversationStore()
    state = await store.create_session()
    session_id = state.session_id

    retrieved = await store.get_session(session_id)
    assert retrieved is not None
    assert retrieved.session_id == session_id


@pytest.mark.asyncio
async def test_store_update_session() -> None:
    """Test updating a session in the store."""
    store = InMemoryConversationStore()
    state = await store.create_session()

    state.add_message(MessageRole.USER, "Test message")
    await store.update_session(state)

    retrieved = await store.get_session(state.session_id)
    assert retrieved is not None
    assert len(retrieved.messages) == 1


@pytest.mark.asyncio
async def test_store_delete_session() -> None:
    """Test deleting a session from the store."""
    store = InMemoryConversationStore()
    state = await store.create_session()
    session_id = state.session_id

    deleted = await store.delete_session(session_id)
    assert deleted is True

    retrieved = await store.get_session(session_id)
    assert retrieved is None


@pytest.mark.asyncio
async def test_store_list_sessions() -> None:
    """Test listing sessions."""
    store = InMemoryConversationStore()

    state1 = await store.create_session()
    state2 = await store.create_session()
    state2.active = False
    await store.update_session(state2)

    all_sessions = await store.list_sessions(active_only=False)
    assert len(all_sessions) == 2

    active_sessions = await store.list_sessions(active_only=True)
    assert len(active_sessions) == 1
    assert active_sessions[0].session_id == state1.session_id
