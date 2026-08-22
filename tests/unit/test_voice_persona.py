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


def _flat(text: str) -> str:
    """The instruction with its line wrapping collapsed.

    Persona text is hard-wrapped, so a phrase worth asserting on routinely
    straddles a newline; matching on the raw string pins the wrap column
    instead of the wording.
    """
    return " ".join(text.split())


class TestBuilderPersona:
    """The Studio's spoken build assistant.

    Native realtime voice cannot call this application's endpoints, so the
    persona must not claim to build anything — the fastest way to make the
    feature feel broken is an assistant that says "done!" and changed nothing.
    """

    def test_is_told_to_act_rather_than_describe(self):
        from src.api.voice.persona import build_builder_instruction

        # The session now declares canvas tools, so the assistant can change the
        # graph while it talks. It used to be told the opposite — "never claim to
        # have finished building" — because it genuinely could not act, and that
        # disclaimer would now make it refuse work it is able to do.
        instruction = build_builder_instruction()
        assert "you can change the canvas yourself" in _flat(instruction)
        assert "Use them." in _flat(instruction)
        assert "Never claim to have finished building" not in _flat(instruction)

    def test_requires_reading_state_before_answering_about_it(self):
        from src.api.voice.persona import build_builder_instruction

        # Guessing at the canvas is the failure that makes a build partner
        # untrustworthy, so reading it is spelled out rather than implied.
        instruction = build_builder_instruction()
        assert "describe_canvas" in _flat(instruction)
        assert "Never guess at the current state." in _flat(instruction)

    def test_treats_deletion_as_different_from_addition(self):
        from src.api.voice.persona import build_builder_instruction

        instruction = build_builder_instruction()
        assert "only remove something when they clearly" in _flat(instruction)

    def test_must_not_pretend_a_failed_call_succeeded(self):
        from src.api.voice.persona import build_builder_instruction

        instruction = build_builder_instruction()
        assert "do not pretend it succeeded" in _flat(instruction)

    def test_always_carries_the_speaking_rules(self):
        from src.api.voice.persona import build_builder_instruction

        assert VOICE_ADDENDUM in build_builder_instruction()

    def test_continues_from_an_existing_draft(self):
        from src.api.voice.persona import build_builder_instruction

        instruction = build_builder_instruction(draft="a bot for course enrolment")
        assert "course enrolment" in instruction
        assert "rather than starting over" in instruction

    def test_no_draft_section_when_empty(self):
        from src.api.voice.persona import build_builder_instruction

        assert "rather than starting over" not in build_builder_instruction(draft="   ")

    def test_stays_within_the_instruction_budget(self):
        from src.api.voice.persona import MAX_INSTRUCTION_CHARS, build_builder_instruction

        assert len(build_builder_instruction(draft="x" * 10000)) <= MAX_INSTRUCTION_CHARS

    def test_teaches_the_platform_vocabulary(self):
        from src.api.voice.persona import build_builder_instruction

        instruction = build_builder_instruction()
        for term in ("agent", "tool", "workflow", "deployment"):
            assert term in instruction
