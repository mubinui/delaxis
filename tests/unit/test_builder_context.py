"""Tests for the Builder's live capability inventory.

The inventory is what stops the Builder inventing tool ids that fail on apply,
so the properties that matter are: it reflects the real config, it stays in
sync when config changes, and a broken config degrades instead of raising —
a Builder that 500s because one JSON file is malformed is worse than one that
plans without the catalogue.
"""

import json

import pytest

from src.api import builder_context
from src.api.builder_context import (
    TOOL_SELECTION_GUIDANCE,
    _summarise,
    agent_inventory,
    allowed_values,
    render_agent_catalogue,
    render_capability_brief,
    render_tool_catalogue,
    tool_inventory,
    workflow_inventory,
)
from src.api.builder_prompts import BUILDER_TYPES, get_builder_prompt


@pytest.fixture
def fake_configs(tmp_path, monkeypatch):
    """A small, known configuration directory."""
    (tmp_path / "tools.json").write_text(json.dumps({
        "version": "1.0",
        "tools": [
            {
                "id": "search_things", "name": "search_things", "category": "research",
                "description": "Search for things.\n\nParameters:\n  - query (required): what to find",
                "entrypoint": "x:y", "enabled": True, "settings": {},
            },
            {
                "id": "shop_db", "name": "shop_db", "category": "data",
                "description": "Query the shop database.",
                "enabled": True,
                "settings": {"type": "sql", "db_uri_env_var": "SHOP_DB_URI"},
            },
            {
                "id": "switched_off", "name": "switched_off", "category": "utilities",
                "description": "Should never appear.",
                "entrypoint": "x:y", "enabled": False, "settings": {},
            },
        ],
    }))
    (tmp_path / "agents.json").write_text(json.dumps({
        "agents": [
            {"id": "triage", "name": "Triage", "description": "Routes requests", "tools": ["search_things"]},
        ]
    }))
    (tmp_path / "workflows.json").write_text(json.dumps({
        "workflows": [
            {"id": "support", "name": "Support", "pattern": "selector", "enabled": True,
             "topology": {"nodes": [{"id": "a"}, {"id": "b"}]}},
        ]
    }))
    monkeypatch.setenv("DELAXIS_CONFIG_DIR", str(tmp_path))
    return tmp_path


class TestToolInventory:
    def test_lists_enabled_tools(self, fake_configs):
        ids = {t["id"] for t in tool_inventory()}
        assert ids == {"search_things", "shop_db"}

    def test_disabled_tools_are_excluded(self, fake_configs):
        # A disabled tool offered to the model is a plan that fails on apply.
        assert "switched_off" not in {t["id"] for t in tool_inventory()}

    def test_carries_category_and_type(self, fake_configs):
        tools = {t["id"]: t for t in tool_inventory()}
        assert tools["shop_db"]["category"] == "data"
        assert tools["shop_db"]["type"] == "sql"
        assert tools["search_things"]["type"] == "function"

    def test_flags_tools_needing_credentials(self, fake_configs):
        tools = {t["id"]: t for t in tool_inventory()}
        assert tools["shop_db"]["needs_config"] is True
        assert tools["search_things"]["needs_config"] is False

    def test_summary_drops_the_parameter_block(self, fake_configs):
        tools = {t["id"]: t for t in tool_inventory()}
        assert tools["search_things"]["summary"] == "Search for things."


class TestSummarise:
    def test_keeps_short_text_whole(self):
        assert _summarise("Does a thing.") == "Does a thing."

    def test_strips_parameters_section(self):
        assert _summarise("Does a thing.\n\nParameters:\n  - x: y") == "Does a thing."

    def test_collapses_whitespace(self):
        assert _summarise("Does   a\n  thing.") == "Does a thing."

    def test_truncates_long_text(self):
        assert len(_summarise("word " * 200)) <= 165

    def test_empty_is_safe(self):
        assert _summarise("") == ""


class TestAgentAndWorkflowInventory:
    def test_lists_agents(self, fake_configs):
        [agent] = agent_inventory()
        assert agent["id"] == "triage"
        assert agent["tools"] == "search_things"

    def test_agent_without_tools_reads_as_none(self, fake_configs, tmp_path):
        (fake_configs / "agents.json").write_text(json.dumps({"agents": [{"id": "a", "name": "A"}]}))
        assert agent_inventory()[0]["tools"] == "none"

    def test_lists_workflows_with_shape(self, fake_configs):
        [workflow] = workflow_inventory()
        assert workflow["pattern"] == "selector"
        assert workflow["nodes"] == "2"


class TestAllowedValues:
    def test_reads_the_real_enums(self):
        values = allowed_values()
        assert "sql" in values["tool_types"]
        assert "mongodb" in values["tool_types"]
        assert "single" in values["patterns"]

    def test_patterns_match_the_api_enum(self):
        from src.config.workflow_models import ConversationPattern

        assert set(allowed_values()["patterns"]) == {m.value for m in ConversationPattern}


class TestRendering:
    def test_catalogue_groups_by_category(self, fake_configs):
        text = render_tool_catalogue()
        assert "RESEARCH" in text and "DATA" in text
        assert "search_things — Search for things." in text

    def test_catalogue_marks_tools_needing_credentials(self, fake_configs):
        assert "needs credentials" in render_tool_catalogue()

    def test_agent_catalogue_renders(self, fake_configs):
        assert "triage" in render_agent_catalogue()

    def test_brief_can_omit_sections(self, fake_configs):
        with_agents = render_capability_brief(include_agents=True, include_workflows=True)
        without = render_capability_brief(include_agents=False, include_workflows=False)
        assert "Agents that already exist" in with_agents
        assert "Agents that already exist" not in without

    def test_brief_names_the_valid_enums(self, fake_configs):
        brief = render_capability_brief()
        assert "Valid tool types" in brief
        assert "Valid workflow patterns" in brief


class TestDegradation:
    def test_missing_config_dir_does_not_raise(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DELAXIS_CONFIG_DIR", str(tmp_path / "nope"))
        assert tool_inventory() == []
        assert "No tools are registered" in render_tool_catalogue()

    def test_malformed_json_does_not_raise(self, tmp_path, monkeypatch):
        (tmp_path / "tools.json").write_text("{not json")
        monkeypatch.setenv("DELAXIS_CONFIG_DIR", str(tmp_path))
        # A broken file must not take the Builder down with it.
        assert tool_inventory() == []
        assert render_capability_brief()

    def test_unexpected_shape_does_not_raise(self, tmp_path, monkeypatch):
        (tmp_path / "tools.json").write_text(json.dumps({"tools": ["not-an-object", 42]}))
        (tmp_path / "agents.json").write_text(json.dumps({"agents": "not-a-list"}))
        monkeypatch.setenv("DELAXIS_CONFIG_DIR", str(tmp_path))
        assert tool_inventory() == []
        assert agent_inventory() == []


class TestFreshness:
    def test_a_newly_added_tool_appears_without_a_restart(self, fake_configs):
        assert "brand_new_tool" not in render_tool_catalogue()

        config = json.loads((fake_configs / "tools.json").read_text())
        config["tools"].append({
            "id": "brand_new_tool", "name": "brand_new_tool", "category": "utilities",
            "description": "Registered a moment ago.", "entrypoint": "x:y",
            "enabled": True, "settings": {},
        })
        (fake_configs / "tools.json").write_text(json.dumps(config))

        # Read fresh per call: a tool registered in the Studio must be usable in
        # the very next build, not after a server restart.
        assert "brand_new_tool" in render_tool_catalogue()


class TestPromptAssembly:
    @pytest.mark.parametrize("builder_type", BUILDER_TYPES)
    def test_every_builder_type_assembles(self, builder_type, fake_configs):
        prompt = get_builder_prompt(builder_type)
        assert len(prompt) > 200

    def test_unknown_type_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown builder type"):
            get_builder_prompt("nonsense")

    @pytest.mark.parametrize("builder_type", ["agent", "tool", "workflow"])
    def test_config_builders_see_the_catalogue(self, builder_type, fake_configs):
        assert "search_things" in get_builder_prompt(builder_type)

    def test_function_builder_omits_the_catalogue(self, fake_configs):
        # Writing a Python function does not involve picking platform tools.
        assert "search_things" not in get_builder_prompt("function")

    def test_only_agent_and_workflow_see_existing_agents(self, fake_configs):
        assert "triage" in get_builder_prompt("agent")
        assert "triage" in get_builder_prompt("workflow")
        assert "triage" not in get_builder_prompt("tool")

    def test_agent_prompt_teaches_the_current_type(self, fake_configs):
        prompt = get_builder_prompt("agent")
        assert '"type": "LlmAgent"' in prompt
        assert "legacy" in prompt.lower()

    def test_tool_prompt_covers_every_valid_type(self, fake_configs):
        prompt = get_builder_prompt("tool")
        for tool_type in allowed_values()["tool_types"]:
            assert tool_type in prompt, f"tool type '{tool_type}' is not documented"

    def test_tool_prompt_forbids_inline_credentials(self, fake_configs):
        assert "Never inline a credential" in get_builder_prompt("tool")

    def test_selection_guidance_is_attached(self, fake_configs):
        assert TOOL_SELECTION_GUIDANCE.splitlines()[0] in get_builder_prompt("agent")

    def test_workflow_prompt_states_the_apply_rules(self, fake_configs):
        prompt = get_builder_prompt("workflow")
        assert "entry_node" in prompt
        assert "must be an agent you defined" in prompt


class TestLegacyMapping:
    def test_mapping_access_still_works(self, fake_configs):
        assert len(builder_context.render_tool_catalogue()) > 0
        from src.api.builder_prompts import BUILDER_PROMPTS

        assert "agent" in BUILDER_PROMPTS
        assert BUILDER_PROMPTS["agent"]
        assert BUILDER_PROMPTS.get("nope") is None
        assert set(BUILDER_PROMPTS.keys()) == set(BUILDER_TYPES)
