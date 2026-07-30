"""Spoken turns must land in the same message history as typed ones.

The payoff is that the deployed page's existing loadHistory() shows a voice
conversation on reload with no frontend change and no schema migration — the
``modality`` marker in the message metadata is the only thing distinguishing them.
"""

import pytest

from src.api.session_manager import SessionManager


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setenv("DELAXIS_DATA_DIR", str(tmp_path))
    instance = SessionManager()
    instance.storage_path = tmp_path / "sessions.json"
    return instance


@pytest.fixture
async def session(manager):
    return await manager.create_session(workflow_id="assistant_chat", user_id="visitor-1")


class TestRecordVoiceTurn:
    @pytest.mark.asyncio
    async def test_writes_both_sides_of_the_exchange(self, manager):
        state = await manager.create_session(workflow_id="assistant_chat", user_id="u")
        recorded = await manager.record_voice_turn(
            state.session_id, user_text="what are the fees", agent_text="twelve thousand a year"
        )
        assert recorded is True

        history = await manager.get_chat_history(state.session_id)
        roles = [(m["role"], m["content"]) for m in history["messages"]]
        assert ("user", "what are the fees") in roles
        assert ("assistant", "twelve thousand a year") in roles

    @pytest.mark.asyncio
    async def test_marks_turns_as_voice(self, manager):
        state = await manager.create_session(workflow_id="assistant_chat", user_id="u")
        await manager.record_voice_turn(
            state.session_id, user_text="hi", agent_text="hello", runtime="gemini_live"
        )
        history = await manager.get_chat_history(state.session_id)
        for message in history["messages"]:
            assert message["metadata"]["modality"] == "voice"
            assert message["metadata"]["runtime"] == "gemini_live"

    @pytest.mark.asyncio
    async def test_increments_the_turn_counter(self, manager):
        state = await manager.create_session(workflow_id="assistant_chat", user_id="u")
        before = (await manager.get_chat_history(state.session_id))["turn_count"]
        await manager.record_voice_turn(state.session_id, user_text="a", agent_text="b")
        after = (await manager.get_chat_history(state.session_id))["turn_count"]
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_interleaves_with_typed_messages(self, manager):
        state = await manager.create_session(workflow_id="assistant_chat", user_id="u")
        from src.memory.models import MessageRole

        state.add_message(MessageRole.USER, "typed question", runtime="crewai")
        await manager.record_voice_turn(state.session_id, user_text="spoken", agent_text="answer")
        history = await manager.get_chat_history(state.session_id)
        contents = [m["content"] for m in history["messages"]]
        assert contents == ["typed question", "spoken", "answer"]


class TestEmptyTurns:
    @pytest.mark.asyncio
    async def test_silence_is_not_recorded(self, manager):
        # Voice activity detection fires on background noise; an empty turn is
        # not worth a row.
        state = await manager.create_session(workflow_id="assistant_chat", user_id="u")
        assert await manager.record_voice_turn(state.session_id, user_text="", agent_text="") is False
        assert (await manager.get_chat_history(state.session_id))["messages"] == []

    @pytest.mark.asyncio
    async def test_whitespace_only_is_not_recorded(self, manager):
        state = await manager.create_session(workflow_id="assistant_chat", user_id="u")
        assert await manager.record_voice_turn(state.session_id, user_text="  ", agent_text="\n") is False

    @pytest.mark.asyncio
    async def test_one_sided_turn_is_recorded(self, manager):
        state = await manager.create_session(workflow_id="assistant_chat", user_id="u")
        assert await manager.record_voice_turn(state.session_id, user_text="hello?", agent_text="") is True
        history = await manager.get_chat_history(state.session_id)
        assert [m["role"] for m in history["messages"]] == ["user"]


class TestUnknownSession:
    @pytest.mark.asyncio
    async def test_returns_false_rather_than_raising(self, manager):
        from uuid import uuid4

        assert await manager.record_voice_turn(uuid4(), user_text="a", agent_text="b") is False
