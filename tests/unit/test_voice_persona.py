"""The realtime model's system instruction.

Native voice bypasses the workflow, so the persona is the only thing making a
spoken answer resemble a typed one. The speaking rules must always survive,
because without them the model emits markdown and bullet lists that get read out
character by character.
"""

from src.api.voice.persona import (
    MAX_INSTRUCTION_CHARS,
    VOICE_ADDENDUM,
    build_system_instruction,
)


class TestPrecedence:
    def test_explicit_prompt_wins(self):
        result = build_system_instruction(
            title="Support", system_prompt="You are Ada, a terse support agent."
        )
        assert "You are Ada, a terse support agent." in result

    def test_falls_back_to_generic_when_nothing_resolves(self):
        result = build_system_instruction(title="Admissions Bot", workflow_id="")
        assert "Admissions Bot" in result

    def test_entry_agent_message_is_used(self, monkeypatch):
        # Mirrors the runtime's own backstory fallback so the voice agent and the
        # text agent describe themselves the same way.
        monkeypatch.setattr(
            "src.api.voice.persona._entry_agent_persona",
            lambda _wf: "You are the admissions assistant for Example University.",
        )
        result = build_system_instruction(title="x", workflow_id="admissions")
        assert "admissions assistant for Example University" in result

    def test_lookup_failure_degrades_to_generic(self, monkeypatch):
        def boom():
            raise RuntimeError("registry unavailable")

        # Patch the dependency, not the lookup itself, so the guard inside
        # _entry_agent_persona is what gets exercised. A persona is a nicety; a
        # broken registry must never fail the voice session.
        monkeypatch.setattr("src.config.workflow_registry.get_workflow_registry", boom)
        result = build_system_instruction(title="Fallback Bot", workflow_id="wf")
        assert "Fallback Bot" in result
        assert VOICE_ADDENDUM in result

    def test_unknown_workflow_degrades_to_generic(self, monkeypatch):
        class EmptyRegistry:
            def get_workflow(self, _workflow_id):
                return None

        monkeypatch.setattr(
            "src.config.workflow_registry.get_workflow_registry", lambda: EmptyRegistry()
        )
        result = build_system_instruction(title="Fallback Bot", workflow_id="missing")
        assert "Fallback Bot" in result


class TestAddendum:
    def test_always_appended(self):
        for kwargs in (
            {"system_prompt": "Custom."},
            {"title": "T"},
            {"system_prompt": "x" * 50},
        ):
            assert VOICE_ADDENDUM in build_system_instruction(**kwargs)

    def test_survives_truncation_of_an_oversized_persona(self):
        result = build_system_instruction(system_prompt="y" * (MAX_INSTRUCTION_CHARS * 2))
        assert len(result) <= MAX_INSTRUCTION_CHARS
        assert VOICE_ADDENDUM in result


class TestRecentConversation:
    def test_includes_recent_turns(self):
        history = [
            {"role": "user", "content": "What are the fees?"},
            {"role": "assistant", "content": "Tuition is 12,000 a year."},
        ]
        result = build_system_instruction(system_prompt="P", history=history)
        assert "What are the fees?" in result
        assert "Tuition is 12,000 a year." in result

    def test_keeps_only_the_tail(self):
        history = [{"role": "user", "content": f"message {i}"} for i in range(30)]
        result = build_system_instruction(system_prompt="P", history=history)
        assert "message 29" in result
        assert "message 0\n" not in result

    def test_skips_non_conversational_entries(self):
        history = [
            {"role": "system", "content": "internal note"},
            {"role": "user", "content": ""},
            {"role": "user", "content": "real question"},
        ]
        result = build_system_instruction(system_prompt="P", history=history)
        assert "internal note" not in result
        assert "real question" in result

    def test_no_history_section_when_empty(self):
        assert "Recent conversation" not in build_system_instruction(system_prompt="P", history=[])
