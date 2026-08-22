"""Tests for the canvas tools a spoken build conversation can call.

The realtime session was audio-only: no tools were declared, so the model could
describe a change but never make one. These cover the wiring that changed that —
the declaration going upstream, the call coming back, and the boundary that
keeps a deployed chatbot's visitor from reaching any of it.
"""

import json

import pytest

from src.api.voice import protocol as p
from src.api.voice.bridge import build_setup_frame
from src.api.voice.canvas_tools import (
    CANVAS_FUNCTIONS,
    DESTRUCTIVE,
    FUNCTION_NAMES,
    build_tool_declaration,
    is_destructive,
)
from src.api.voice.config import LiveVoiceConfig


@pytest.fixture
def config():
    # Mirrors the fixture in test_voice_bridge.py so both exercise the same shape.
    return LiveVoiceConfig(
        provider_id="gemini",
        protocol="bidi_generate_content_v1beta",
        ws_url="wss://upstream.test/ws",
        auth_query_param="key",
        model="gemini-3.1-flash-live-preview",
        model_prefix="models/",
        input_sample_rate=16000,
        input_mime_type="audio/pcm;rate=16000",
        output_sample_rate=24000,
        max_session_seconds=300,
    )


class TestDeclaration:
    def test_every_function_has_a_description(self):
        # The description is the only thing telling the model when to call it.
        for function in CANVAS_FUNCTIONS:
            assert function.get("description"), f"{function['name']} has no description"

    def test_every_function_declares_parameters(self):
        for function in CANVAS_FUNCTIONS:
            assert function["parameters"]["type"] == "OBJECT"

    def test_required_parameters_are_declared_properties(self):
        for function in CANVAS_FUNCTIONS:
            properties = function["parameters"].get("properties", {})
            for name in function["parameters"].get("required", []):
                assert name in properties, f"{function['name']}: '{name}' required but not declared"

    def test_covers_the_operations_a_build_conversation_needs(self):
        expected = {
            "add_agent", "add_tool", "add_trigger", "connect",
            "set_instruction", "set_model", "remove_node",
            "describe_canvas", "list_available_tools", "fix_problems",
        }
        assert expected <= FUNCTION_NAMES

    def test_declaration_is_shaped_for_the_live_api(self):
        declaration = build_tool_declaration()
        assert isinstance(declaration, list)
        assert "functionDeclarations" in declaration[0]
        assert len(declaration[0]["functionDeclarations"]) == len(CANVAS_FUNCTIONS)


class TestDestructive:
    def test_removal_is_marked(self):
        assert is_destructive("remove_node")

    def test_ordinary_edits_are_not(self):
        for name in ("add_agent", "add_tool", "connect", "set_model", "describe_canvas"):
            assert not is_destructive(name), f"{name} should not need confirmation"

    def test_every_destructive_name_is_a_real_function(self):
        assert DESTRUCTIVE <= FUNCTION_NAMES | {"clear_canvas"}


class TestSetupFrame:
    def test_tools_are_absent_when_none_are_passed(self, config):
        # A deployed chatbot's session must stay audio-only.
        frame = build_setup_frame(config, system_instruction="hi")
        assert "tools" not in frame["setup"]

    def test_tools_are_declared_when_passed(self, config):
        frame = build_setup_frame(
            config, system_instruction="hi", tools=build_tool_declaration()
        )
        declared = frame["setup"]["tools"][0]["functionDeclarations"]
        assert {f["name"] for f in declared} == FUNCTION_NAMES

    def test_declaring_tools_does_not_disturb_the_rest_of_setup(self, config):
        plain = build_setup_frame(config, system_instruction="hi", voice_name="Kore")
        with_tools = build_setup_frame(
            config, system_instruction="hi", voice_name="Kore", tools=build_tool_declaration()
        )
        for key in ("model", "generationConfig", "systemInstruction",
                    "inputAudioTranscription", "outputAudioTranscription"):
            assert plain["setup"][key] == with_tools["setup"][key]

    def test_frame_is_json_serialisable(self, config):
        # It goes onto a WebSocket as JSON; a non-serialisable value would only
        # surface at connection time.
        frame = build_setup_frame(
            config, system_instruction="hi", tools=build_tool_declaration()
        )
        assert json.loads(json.dumps(frame))["setup"]["tools"]


class TestProtocol:
    def test_tool_frames_are_registered_both_ways(self):
        assert p.SERVER_TOOL_CALL in p.SERVER_FRAME_TYPES
        assert p.CLIENT_TOOL_RESULT in p.CLIENT_FRAME_TYPES

    def test_existing_frames_are_untouched(self):
        # Deployed chat pages speak this protocol; adding to it must not move
        # anything already in it.
        for name in ("ready", "user_text", "agent_text", "interrupted", "turn_end"):
            assert name in p.SERVER_FRAME_TYPES
        for name in ("stop", "bye"):
            assert name in p.CLIENT_FRAME_TYPES


class TestSessionScope:
    def test_only_builder_sessions_receive_tools(self):
        """A visitor to a deployed chatbot must not be able to edit a workflow.

        The router decides this, so the assertion is on the source rather than
        on a live socket: the tools argument is gated on the ticket purpose.
        """
        from pathlib import Path

        source = Path("src/api/routers/voice.py").read_text()
        assert "tools=build_tool_declaration() if purpose == tickets.PURPOSE_BUILDER else None" in source
