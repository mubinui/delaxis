"""
Property-based tests for referential integrity validation.

**Feature: industry-grade-orchestration, Property 22: Referential integrity validation**
**Validates: Requirements 8.4**
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.config.agent_models import AgentType, HumanInputMode
from src.config.config_manager import ConfigurationManager
from src.config.workflow_models import ConversationPattern


@st.composite
def valid_agent_id(draw):
    """Generate valid agent IDs (lowercase alphanumeric with underscores)."""
    # Generate ID that matches ^[a-z0-9_]+$ and starts with a letter
    length = draw(st.integers(min_value=3, max_value=20))
    first_char = draw(st.sampled_from("abcdefghijklmnopqrstuvwxyz"))
    rest_chars = draw(
        st.lists(
            st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_"),
            min_size=length - 1,
            max_size=length - 1,
        )
    )
    return first_char + "".join(rest_chars)


@st.composite
def agent_config(draw, agent_id):
    """Generate agent configuration with specific ID."""
    return {
        "id": agent_id,
        "type": AgentType.CONVERSABLE.value,
        "name": f"Agent {agent_id}",
        "system_message": "Test system message",
        "llm_config": {"provider_id": "test_provider", "model": "test-model", "temperature": 0.7},
        "human_input_mode": HumanInputMode.NEVER.value,
        "max_consecutive_auto_reply": 10,
    }


@st.composite
def agents_config_with_ids(draw, agent_ids):
    """Generate agents configuration with specific agent IDs."""
    agents = [draw(agent_config(agent_id)) for agent_id in agent_ids]
    return {"version": "1.0", "agents": agents}


@st.composite
def two_agent_workflow(draw, entry_agent_id, recipient_agent_id):
    """Generate two-agent workflow configuration."""
    # Generate workflow ID that matches ^[a-z0-9_-]+$ and starts with a letter
    length = draw(st.integers(min_value=3, max_value=20))
    first_char = draw(st.sampled_from("abcdefghijklmnopqrstuvwxyz"))
    rest_chars = draw(
        st.lists(
            st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_-"),
            min_size=length - 1,
            max_size=length - 1,
        )
    )
    workflow_id = first_char + "".join(rest_chars)

    return {
        "id": workflow_id,
        "name": f"Workflow {workflow_id}",
        "description": "Test workflow",
        "pattern": ConversationPattern.TWO_AGENT.value,
        "topology": {
            "type": "sequential",
            "nodes": [
                {"id": "entry", "agent_id": entry_agent_id, "description": "Entry"},
                {"id": "recipient", "agent_id": recipient_agent_id, "description": "Recipient"},
            ],
            "entry_node": "entry",
        },
        "enabled": True,
        "metadata": {},
    }


@st.composite
def sequential_workflow(draw, agent_ids):
    """Generate sequential workflow configuration."""
    assume(len(agent_ids) >= 2)

    # Generate workflow ID that matches ^[a-z0-9_-]+$ and starts with a letter
    length = draw(st.integers(min_value=3, max_value=20))
    first_char = draw(st.sampled_from("abcdefghijklmnopqrstuvwxyz"))
    rest_chars = draw(
        st.lists(
            st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_-"),
            min_size=length - 1,
            max_size=length - 1,
        )
    )
    workflow_id = first_char + "".join(rest_chars)

    # Create topology nodes and edges from the agent IDs
    nodes = [
        {"id": f"node_{i}", "agent_id": agent_id, "description": f"Step {i}"}
        for i, agent_id in enumerate(agent_ids)
    ]
    edges = [
        {"from_node": f"node_{i}", "to_node": f"node_{i + 1}", "context_strategy": "full"}
        for i in range(len(agent_ids) - 1)
    ]

    return {
        "id": workflow_id,
        "name": f"Workflow {workflow_id}",
        "description": "Test sequential workflow",
        "pattern": ConversationPattern.SEQUENTIAL.value,
        "topology": {
            "type": "sequential",
            "nodes": nodes,
            "edges": edges,
            "entry_node": "node_0",
        },
        "enabled": True,
        "metadata": {},
    }


@st.composite
def group_chat_workflow(draw, agent_ids):
    """Generate group chat workflow configuration."""
    assume(len(agent_ids) >= 2)

    # Generate workflow ID that matches ^[a-z0-9_-]+$ and starts with a letter
    length = draw(st.integers(min_value=3, max_value=20))
    first_char = draw(st.sampled_from("abcdefghijklmnopqrstuvwxyz"))
    rest_chars = draw(
        st.lists(
            st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_-"),
            min_size=length - 1,
            max_size=length - 1,
        )
    )
    workflow_id = first_char + "".join(rest_chars)

    return {
        "id": workflow_id,
        "name": f"Workflow {workflow_id}",
        "description": "Test group chat workflow",
        "pattern": ConversationPattern.GROUP_CHAT.value,
        "topology": {
            "type": "graph",
            "nodes": [
                {"id": f"node_{i}", "agent_id": agent_id, "description": f"Member {i}"}
                for i, agent_id in enumerate(agent_ids)
            ],
            "entry_node": "node_0",
        },
        "enabled": True,
        "metadata": {},
    }


class TestReferentialIntegrityValidation:
    """
    Property 22: Referential integrity validation

    For any configuration with references to non-existent agents or tools,
    validation should fail with errors identifying the invalid references.

    Validates: Requirements 8.4
    """

    @settings(max_examples=100)
    @given(
        agent_ids=st.lists(valid_agent_id(), min_size=2, max_size=5, unique=True), data=st.data()
    )
    def test_valid_references_accepted(self, agent_ids, data):
        """
        Property: Workflows referencing existing agents should pass validation.

        For any workflow that references only agents that exist in the agents config,
        referential integrity validation should succeed.
        """
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            # Write agents config
            agents_file = config_dir / "agents.json"
            agents_data = data.draw(agents_config_with_ids(agent_ids))
            with open(agents_file, "w") as f:
                json.dump(agents_data, f)

            # Write workflow config referencing these agents
            workflows_file = config_dir / "workflows.json"
            workflow = data.draw(two_agent_workflow(agent_ids[0], agent_ids[1]))
            workflows_data = {"version": "1.0", "workflows": [workflow]}
            with open(workflows_file, "w") as f:
                json.dump(workflows_data, f)

            # Check referential integrity
            manager = ConfigurationManager(config_dir)
            result = manager.check_referential_integrity()

            # Should be valid
            assert result.valid
            assert len(result.errors) == 0

    @settings(max_examples=100)
    @given(
        existing_agent_ids=st.lists(valid_agent_id(), min_size=2, max_size=5, unique=True),
        non_existent_agent_id=valid_agent_id(),
        data=st.data(),
    )
    def test_invalid_agent_reference_rejected(
        self, existing_agent_ids, non_existent_agent_id, data
    ):
        """
        Property: Workflows referencing non-existent agents should fail validation.

        For any workflow that references an agent ID not in the agents config,
        referential integrity validation should fail with an error identifying
        the missing agent.
        """
        # Ensure non-existent ID is actually not in the list
        assume(non_existent_agent_id not in existing_agent_ids)

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            # Write agents config with existing agents
            agents_file = config_dir / "agents.json"
            agents_data = data.draw(agents_config_with_ids(existing_agent_ids))
            with open(agents_file, "w") as f:
                json.dump(agents_data, f)

            # Write workflow config referencing non-existent agent
            workflows_file = config_dir / "workflows.json"
            workflow = data.draw(two_agent_workflow(existing_agent_ids[0], non_existent_agent_id))
            workflows_data = {"version": "1.0", "workflows": [workflow]}
            with open(workflows_file, "w") as f:
                json.dump(workflows_data, f)

            # Check referential integrity
            manager = ConfigurationManager(config_dir)
            result = manager.check_referential_integrity()

            # Should be invalid
            assert not result.valid
            assert len(result.errors) > 0

            # Error should mention the non-existent agent
            error_text = " ".join(result.errors).lower()
            assert non_existent_agent_id.lower() in error_text

    @settings(max_examples=100)
    @given(
        agent_ids=st.lists(valid_agent_id(), min_size=3, max_size=5, unique=True), data=st.data()
    )
    def test_sequential_workflow_referential_integrity(self, agent_ids, data):
        """
        Property: Sequential workflows should validate all agent references.

        For any sequential workflow, all agents referenced in steps should
        exist in the agents configuration.
        """
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            # Write agents config
            agents_file = config_dir / "agents.json"
            agents_data = data.draw(agents_config_with_ids(agent_ids))
            with open(agents_file, "w") as f:
                json.dump(agents_data, f)

            # Write sequential workflow
            workflows_file = config_dir / "workflows.json"
            workflow = data.draw(sequential_workflow(agent_ids))
            workflows_data = {"version": "1.0", "workflows": [workflow]}
            with open(workflows_file, "w") as f:
                json.dump(workflows_data, f)

            # Check referential integrity
            manager = ConfigurationManager(config_dir)
            result = manager.check_referential_integrity()

            # Should be valid
            assert result.valid
            assert len(result.errors) == 0

    @settings(max_examples=100)
    @given(
        agent_ids=st.lists(valid_agent_id(), min_size=2, max_size=5, unique=True), data=st.data()
    )
    def test_group_chat_workflow_referential_integrity(self, agent_ids, data):
        """
        Property: Group chat workflows should validate all agent references.

        For any group chat workflow, all agents in the group_chat.agents list
        should exist in the agents configuration.
        """
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            # Write agents config
            agents_file = config_dir / "agents.json"
            agents_data = data.draw(agents_config_with_ids(agent_ids))
            with open(agents_file, "w") as f:
                json.dump(agents_data, f)

            # Write group chat workflow
            workflows_file = config_dir / "workflows.json"
            workflow = data.draw(group_chat_workflow(agent_ids))
            workflows_data = {"version": "1.0", "workflows": [workflow]}
            with open(workflows_file, "w") as f:
                json.dump(workflows_data, f)

            # Check referential integrity
            manager = ConfigurationManager(config_dir)
            result = manager.check_referential_integrity()

            # Should be valid
            assert result.valid
            assert len(result.errors) == 0

    @settings(max_examples=100)
    @given(
        existing_agent_ids=st.lists(valid_agent_id(), min_size=2, max_size=4, unique=True),
        missing_agent_ids=st.lists(valid_agent_id(), min_size=1, max_size=2, unique=True),
        data=st.data(),
    )
    def test_multiple_missing_agents_all_reported(
        self, existing_agent_ids, missing_agent_ids, data
    ):
        """
        Property: All missing agent references should be reported.

        For any workflow referencing multiple non-existent agents,
        all missing agents should be identified in the error messages.
        """
        # Ensure missing IDs are not in existing IDs
        assume(not any(mid in existing_agent_ids for mid in missing_agent_ids))

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            # Write agents config with existing agents only
            agents_file = config_dir / "agents.json"
            agents_data = data.draw(agents_config_with_ids(existing_agent_ids))
            with open(agents_file, "w") as f:
                json.dump(agents_data, f)

            # Create workflow referencing both existing and missing agents
            all_agent_ids = existing_agent_ids + missing_agent_ids
            workflows_file = config_dir / "workflows.json"
            workflow = data.draw(group_chat_workflow(all_agent_ids))
            workflows_data = {"version": "1.0", "workflows": [workflow]}
            with open(workflows_file, "w") as f:
                json.dump(workflows_data, f)

            # Check referential integrity
            manager = ConfigurationManager(config_dir)
            result = manager.check_referential_integrity()

            # Should be invalid
            assert not result.valid
            assert len(result.errors) > 0

            # All missing agents should be mentioned
            error_text = " ".join(result.errors).lower()
            for missing_id in missing_agent_ids:
                assert missing_id.lower() in error_text

    @settings(max_examples=100)
    @given(
        agent_ids=st.lists(valid_agent_id(), min_size=2, max_size=5, unique=True), data=st.data()
    )
    def test_multiple_workflows_referential_integrity(self, agent_ids, data):
        """
        Property: Referential integrity should validate all workflows.

        For any configuration with multiple workflows, referential integrity
        should be checked for all workflows, not just the first one.
        """
        assume(len(agent_ids) >= 3)

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            # Write agents config
            agents_file = config_dir / "agents.json"
            agents_data = data.draw(agents_config_with_ids(agent_ids))
            with open(agents_file, "w") as f:
                json.dump(agents_data, f)

            # Write multiple workflows with unique IDs
            workflows_file = config_dir / "workflows.json"
            workflow1 = data.draw(two_agent_workflow(agent_ids[0], agent_ids[1]))
            workflow2 = data.draw(two_agent_workflow(agent_ids[1], agent_ids[2]))

            # Ensure unique workflow IDs
            if workflow1["id"] == workflow2["id"]:
                workflow2["id"] = workflow2["id"] + "_2"

            workflows_data = {"version": "1.0", "workflows": [workflow1, workflow2]}
            with open(workflows_file, "w") as f:
                json.dump(workflows_data, f)

            # Check referential integrity
            manager = ConfigurationManager(config_dir)
            result = manager.check_referential_integrity()

            # Should be valid
            assert result.valid
            assert len(result.errors) == 0
