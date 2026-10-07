"""Property-based tests for dependency validation."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.config.dependency_validation import DependencyError, DependencyValidator
from src.config.loader import ConfigurationLoader


# Helper strategies for generating valid IDs
def valid_id_strategy(prefix=""):
    """Generate valid configuration IDs (ASCII only for compatibility)."""
    return (
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
            min_size=1,
            max_size=20,
        )
        .filter(lambda x: x and x[0].isalpha())
        .map(lambda x: f"{prefix}{x}" if prefix else x)
    )


# **Feature: config-management-ui, Property 6: Dependency validation**
@given(
    agent_id=valid_id_strategy("agent_"),
    tool_ids=st.lists(valid_id_strategy("tool_"), min_size=1, max_size=5, unique=True),
    available_tools=st.lists(valid_id_strategy("tool_"), min_size=0, max_size=10, unique=True),
)
@settings(max_examples=100)
def test_agent_tool_reference_validation(agent_id, tool_ids, available_tools):
    """
    Test that agent tool references are validated correctly.

    For any agent configuration referencing tools, all referenced tool IDs
    should exist in the tools configuration.

    Validates: Requirements 5.3, 8.2
    """
    # Create temporary directory for test configs
    with TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)

        # Create tools configuration
        tools_config = {
            "version": "1.0",
            "tools": [
                {
                    "id": tool_id,
                    "name": tool_id,
                    "description": f"Tool {tool_id}",
                    "entrypoint": f"module:{tool_id}",
                    "enabled": True,
                    "settings": {},
                }
                for tool_id in available_tools
            ],
        }

        tools_path = config_dir / "tools.json"
        with open(tools_path, "w") as f:
            json.dump(tools_config, f)

        # Create validator with custom config directory
        loader = ConfigurationLoader(config_dir)
        validator = DependencyValidator(loader)

        # Determine if validation should pass or fail
        missing_tools = [tid for tid in tool_ids if tid not in available_tools]
        should_fail = len(missing_tools) > 0

        if should_fail:
            # Validation should fail with DependencyError
            with pytest.raises(DependencyError) as exc_info:
                validator.validate_agent_tool_references(agent_id, tool_ids)

            # Check error details
            error = exc_info.value
            assert len(error.missing) > 0
            assert all(tid in error.missing for tid in missing_tools)
            assert agent_id in str(error)
        else:
            # Validation should pass without raising an error
            validator.validate_agent_tool_references(agent_id, tool_ids)


# **Feature: config-management-ui, Property 6: Dependency validation**
@given(
    workflow_id=valid_id_strategy("workflow_"),
    agent_ids=st.lists(valid_id_strategy("agent_"), min_size=1, max_size=5, unique=True),
    available_agents=st.lists(valid_id_strategy("agent_"), min_size=0, max_size=10, unique=True),
)
@settings(max_examples=100)
def test_workflow_agent_reference_validation(workflow_id, agent_ids, available_agents):
    """
    Test that workflow agent references are validated correctly.

    For any workflow configuration referencing agents, all referenced agent IDs
    should exist in the agents configuration.

    Validates: Requirements 5.3, 8.2
    """
    # Create temporary directory for test configs
    with TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)

        # Create agents configuration
        agents_config = {
            "version": "1.0",
            "agents": [
                {
                    "id": agent_id,
                    "type": "conversable",
                    "name": agent_id,
                    "system_message": f"Agent {agent_id}",
                    "llm_config": {
                        "provider_id": "openai",
                        "model": "gpt-4",
                    },
                    "tools": [],
                }
                for agent_id in available_agents
            ],
        }

        agents_path = config_dir / "agents.json"
        with open(agents_path, "w") as f:
            json.dump(agents_config, f)

        # Create validator with custom config directory
        loader = ConfigurationLoader(config_dir)
        validator = DependencyValidator(loader)

        # Determine if validation should pass or fail
        missing_agents = [aid for aid in agent_ids if aid not in available_agents]
        should_fail = len(missing_agents) > 0

        if should_fail:
            # Validation should fail with DependencyError
            with pytest.raises(DependencyError) as exc_info:
                validator.validate_workflow_agent_references(workflow_id, set(agent_ids))

            # Check error details
            error = exc_info.value
            assert len(error.missing) > 0
            assert all(aid in error.missing for aid in missing_agents)
            assert workflow_id in str(error)
        else:
            # Validation should pass without raising an error
            validator.validate_workflow_agent_references(workflow_id, set(agent_ids))


# **Feature: config-management-ui, Property 6: Dependency validation**
@given(
    tool_id=valid_id_strategy("tool_"),
    dependent_agents=st.lists(valid_id_strategy("agent_"), min_size=0, max_size=5, unique=True),
)
@settings(max_examples=100)
def test_tool_deletion_validation(tool_id, dependent_agents):
    """
    Test that tool deletion is validated correctly based on dependencies.

    For any tool, if it is referenced by agents, deletion should be rejected.
    If no agents reference it, deletion should be allowed.

    Validates: Requirements 5.3, 8.2
    """
    # Create temporary directory for test configs
    with TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)

        # Create agents configuration with some agents referencing the tool
        agents_config = {
            "version": "1.0",
            "agents": [
                {
                    "id": agent_id,
                    "type": "conversable",
                    "name": agent_id,
                    "system_message": f"Agent {agent_id}",
                    "llm_config": {
                        "provider_id": "openai",
                        "model": "gpt-4",
                    },
                    "tools": [tool_id],  # This agent uses the tool
                }
                for agent_id in dependent_agents
            ],
        }

        agents_path = config_dir / "agents.json"
        with open(agents_path, "w") as f:
            json.dump(agents_config, f)

        # Create validator with custom config directory
        loader = ConfigurationLoader(config_dir)
        validator = DependencyValidator(loader)

        # Determine if deletion should be allowed
        has_dependencies = len(dependent_agents) > 0

        if has_dependencies:
            # Deletion should fail with DependencyError
            with pytest.raises(DependencyError) as exc_info:
                validator.validate_tool_deletion(tool_id)

            # Check error details
            error = exc_info.value
            assert len(error.dependents) > 0
            assert all(aid in error.dependents for aid in dependent_agents)
            assert tool_id in str(error)
        else:
            # Deletion should be allowed without raising an error
            validator.validate_tool_deletion(tool_id)


# **Feature: config-management-ui, Property 6: Dependency validation**
@given(
    agent_id=valid_id_strategy("agent_"),
    dependent_workflows=st.lists(
        valid_id_strategy("workflow_"), min_size=0, max_size=5, unique=True
    ),
)
@settings(max_examples=100)
def test_agent_deletion_validation(agent_id, dependent_workflows):
    """
    Test that agent deletion is validated correctly based on dependencies.

    For any agent, if it is referenced by workflows, deletion should be rejected.
    If no workflows reference it, deletion should be allowed.

    Validates: Requirements 5.3, 8.2
    """
    # Create temporary directory for test configs
    with TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir)

        # Create workflows configuration with some workflows referencing the agent
        workflows_config = {
            "version": "1.0",
            "workflows": [
                {
                    "id": workflow_id,
                    "name": workflow_id,
                    "description": f"Workflow {workflow_id}",
                    "pattern": "sequential",
                    "topology": {
                        "type": "sequential",
                        "nodes": [
                            {"id": "entry", "agent_id": agent_id, "description": "Entry"},
                            {
                                "id": "recipient",
                                "agent_id": "other_agent",
                                "description": "Recipient",
                            },
                        ],
                        "entry_node": "entry",
                    },
                    "enabled": True,
                }
                for workflow_id in dependent_workflows
            ],
        }

        workflows_path = config_dir / "workflows.json"
        with open(workflows_path, "w") as f:
            json.dump(workflows_config, f)

        # Create validator with custom config directory
        loader = ConfigurationLoader(config_dir)
        validator = DependencyValidator(loader)

        # Determine if deletion should be allowed
        has_dependencies = len(dependent_workflows) > 0

        if has_dependencies:
            # Deletion should fail with DependencyError
            with pytest.raises(DependencyError) as exc_info:
                validator.validate_agent_deletion(agent_id)

            # Check error details
            error = exc_info.value
            assert len(error.dependents) > 0
            assert all(wid in error.dependents for wid in dependent_workflows)
            assert agent_id in str(error)
        else:
            # Deletion should be allowed without raising an error
            validator.validate_agent_deletion(agent_id)
