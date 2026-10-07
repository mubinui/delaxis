"""
Property-based tests for hot reload isolation.

**Feature: industry-grade-orchestration, Property 21: Hot reload isolation**
**Validates: Requirements 8.3**
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from src.config.agent_models import AgentType, HumanInputMode
from src.config.config_manager import ConfigurationManager


@st.composite
def valid_agent_config(draw):
    """Generate valid agent configuration."""
    agent_id_length = draw(st.integers(min_value=3, max_value=15))
    first_char = draw(st.sampled_from("abcdefghijklmnopqrstuvwxyz"))
    rest_chars = draw(
        st.lists(
            st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_"),
            min_size=agent_id_length - 1,
            max_size=agent_id_length - 1,
        )
    )
    agent_id = first_char + "".join(rest_chars)

    name_length = draw(st.integers(min_value=3, max_value=20))
    name_first = draw(st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
    name_rest = draw(
        st.lists(
            st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"),
            min_size=name_length - 1,
            max_size=name_length - 1,
        )
    )
    agent_name = name_first + "".join(name_rest)

    return {
        "id": agent_id,
        "type": AgentType.CONVERSABLE.value,
        "name": agent_name,
        "system_message": draw(st.text(min_size=10, max_size=100)),
        "llm_config": {
            "provider_id": "openrouter",
            "model": "openai/gpt-oss-20b",
            "temperature": draw(st.floats(min_value=0.0, max_value=2.0)),
        },
        "human_input_mode": draw(st.sampled_from([mode.value for mode in HumanInputMode])),
        "max_consecutive_auto_reply": draw(st.integers(min_value=1, max_value=20)),
    }


@st.composite
def modified_agent_config(draw, original_config):
    """Generate a modified version of an agent configuration."""
    modified = original_config.copy()

    # Modify one field
    modification_choice = draw(st.integers(min_value=0, max_value=2))

    if modification_choice == 0:
        # Modify system message
        modified["system_message"] = draw(st.text(min_size=10, max_size=100))
    elif modification_choice == 1:
        # Modify temperature
        modified["llm_config"] = modified["llm_config"].copy()
        modified["llm_config"]["temperature"] = draw(st.floats(min_value=0.0, max_value=2.0))
    else:
        # Modify max_consecutive_auto_reply
        modified["max_consecutive_auto_reply"] = draw(st.integers(min_value=1, max_value=20))

    return modified


class TestHotReloadIsolation:
    """
    Property 21: Hot reload isolation

    For any valid configuration change, active sessions should continue with old
    configuration while new sessions should use the new configuration.

    Validates: Requirements 8.3
    """

    @settings(max_examples=100, deadline=None)
    @given(original_config=valid_agent_config(), data=st.data())
    @pytest.mark.asyncio
    async def test_active_sessions_use_old_config(self, original_config, data):
        """
        Property: Active sessions continue with old configuration after reload.

        For any valid configuration change, sessions that were created before
        the change should continue using the original configuration.
        """
        # Generate modified config
        modified_config = data.draw(modified_agent_config(original_config))

        # Ensure configs are actually different
        assume(
            original_config["system_message"] != modified_config["system_message"]
            or original_config["llm_config"]["temperature"]
            != modified_config["llm_config"]["temperature"]
            or original_config["max_consecutive_auto_reply"]
            != modified_config["max_consecutive_auto_reply"]
        )

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            agents_file = config_dir / "agents.json"

            # Write original config
            original_agents_config = {"version": "1.0", "agents": [original_config]}
            with open(agents_file, "w") as f:
                json.dump(original_agents_config, f)

            # Create config manager with hot reload disabled for this test
            config_manager = ConfigurationManager(config_dir)

            # Load original config
            agents_config_v1 = config_manager.load_agents_config(use_cache=False)
            agent_v1 = agents_config_v1.get_agent(original_config["id"])

            # Verify original config loaded
            assert agent_v1 is not None
            assert agent_v1.system_message == original_config["system_message"]

            # Simulate active session using original config
            # Store the original config values
            original_system_message = agent_v1.system_message
            original_temperature = agent_v1.llm_config.temperature if agent_v1.llm_config else None
            original_max_reply = agent_v1.max_consecutive_auto_reply

            # Write modified config
            modified_agents_config = {"version": "1.0", "agents": [modified_config]}
            with open(agents_file, "w") as f:
                json.dump(modified_agents_config, f)

            # Load new config (simulating hot reload)
            agents_config_v2 = config_manager.load_agents_config(use_cache=False)
            agent_v2 = agents_config_v2.get_agent(modified_config["id"])

            # Verify new config loaded
            assert agent_v2 is not None
            assert agent_v2.system_message == modified_config["system_message"]

            # Original agent config should still have original values (isolation)
            # This simulates that active sessions keep their agent instances
            assert agent_v1.system_message == original_system_message
            assert agent_v1.max_consecutive_auto_reply == original_max_reply
            if original_temperature is not None:
                assert agent_v1.llm_config.temperature == original_temperature

            # New config should have modified values
            assert agent_v2.system_message == modified_config["system_message"]
            assert (
                agent_v2.max_consecutive_auto_reply == modified_config["max_consecutive_auto_reply"]
            )

    @settings(max_examples=100, deadline=None)
    @given(original_config=valid_agent_config(), data=st.data())
    @pytest.mark.asyncio
    async def test_new_sessions_use_new_config(self, original_config, data):
        """
        Property: New sessions use new configuration after reload.

        For any valid configuration change, sessions created after the change
        should use the new configuration.
        """
        # Generate modified config
        modified_config = data.draw(modified_agent_config(original_config))

        # Ensure configs are actually different
        assume(
            original_config["system_message"] != modified_config["system_message"]
            or original_config["llm_config"]["temperature"]
            != modified_config["llm_config"]["temperature"]
        )

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            agents_file = config_dir / "agents.json"

            # Write original config
            original_agents_config = {"version": "1.0", "agents": [original_config]}
            with open(agents_file, "w") as f:
                json.dump(original_agents_config, f)

            # Create config manager
            config_manager = ConfigurationManager(config_dir)

            # Load original config
            agents_config_v1 = config_manager.load_agents_config(use_cache=False)
            agent_v1 = agents_config_v1.get_agent(original_config["id"])

            # Verify original config
            assert agent_v1.system_message == original_config["system_message"]

            # Write modified config
            modified_agents_config = {"version": "1.0", "agents": [modified_config]}
            with open(agents_file, "w") as f:
                json.dump(modified_agents_config, f)

            # Load new config (simulating hot reload for new session)
            agents_config_v2 = config_manager.load_agents_config(use_cache=False)
            agent_v2 = agents_config_v2.get_agent(modified_config["id"])

            # New session should use new config
            assert agent_v2.system_message == modified_config["system_message"]
            assert (
                agent_v2.max_consecutive_auto_reply == modified_config["max_consecutive_auto_reply"]
            )

    @settings(max_examples=100, deadline=None)
    @given(original_config=valid_agent_config(), data=st.data())
    @pytest.mark.asyncio
    async def test_config_reload_does_not_affect_active_sessions(self, original_config, data):
        """
        Property: Configuration reload does not disrupt active sessions.

        For any configuration reload, active sessions should continue to function
        normally without errors or interruptions.
        """
        # Generate modified config
        modified_config = data.draw(modified_agent_config(original_config))

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            agents_file = config_dir / "agents.json"

            # Write original config
            original_agents_config = {"version": "1.0", "agents": [original_config]}
            with open(agents_file, "w") as f:
                json.dump(original_agents_config, f)

            # Create config manager
            config_manager = ConfigurationManager(config_dir)

            # Load original config
            agents_config_v1 = config_manager.load_agents_config(use_cache=False)
            agent_v1 = agents_config_v1.get_agent(original_config["id"])

            # Simulate active session state
            active_session_agent_id = agent_v1.id
            active_session_system_message = agent_v1.system_message

            # Write modified config (hot reload)
            modified_agents_config = {"version": "1.0", "agents": [modified_config]}
            with open(agents_file, "w") as f:
                json.dump(modified_agents_config, f)

            # Reload config
            agents_config_v2 = config_manager.load_agents_config(use_cache=False)

            # Active session should still have access to its original agent config
            # (in practice, the session would have cached the agent instance)
            assert agent_v1.id == active_session_agent_id
            assert agent_v1.system_message == active_session_system_message

            # New config should be available for new sessions
            agent_v2 = agents_config_v2.get_agent(modified_config["id"])
            assert agent_v2.system_message == modified_config["system_message"]

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.filter_too_much])
    @given(config1=valid_agent_config(), data=st.data())
    @pytest.mark.asyncio
    async def test_multiple_reloads_maintain_isolation(self, config1, data):
        """
        Property: Multiple configuration reloads maintain isolation.

        For any sequence of configuration changes, each session should maintain
        the configuration it was created with, regardless of subsequent reloads.
        """
        # Generate two more configs
        config2 = data.draw(modified_agent_config(config1))
        config3 = data.draw(modified_agent_config(config2))

        # Ensure all configs are different
        assume(config1["system_message"] != config2["system_message"])
        assume(config2["system_message"] != config3["system_message"])
        assume(config1["system_message"] != config3["system_message"])

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            agents_file = config_dir / "agents.json"

            config_manager = ConfigurationManager(config_dir)

            # Load config1
            with open(agents_file, "w") as f:
                json.dump({"version": "1.0", "agents": [config1]}, f)
            agents_v1 = config_manager.load_agents_config(use_cache=False)
            agent_v1 = agents_v1.get_agent(config1["id"])
            session1_message = agent_v1.system_message

            # Load config2
            with open(agents_file, "w") as f:
                json.dump({"version": "1.0", "agents": [config2]}, f)
            agents_v2 = config_manager.load_agents_config(use_cache=False)
            agent_v2 = agents_v2.get_agent(config2["id"])
            session2_message = agent_v2.system_message

            # Load config3
            with open(agents_file, "w") as f:
                json.dump({"version": "1.0", "agents": [config3]}, f)
            agents_v3 = config_manager.load_agents_config(use_cache=False)
            agent_v3 = agents_v3.get_agent(config3["id"])
            session3_message = agent_v3.system_message

            # Each agent instance should maintain its original config
            assert agent_v1.system_message == session1_message == config1["system_message"]
            assert agent_v2.system_message == session2_message == config2["system_message"]
            assert agent_v3.system_message == session3_message == config3["system_message"]

            # All three should be different
            assert session1_message != session2_message
            assert session2_message != session3_message
            assert session1_message != session3_message

    @settings(max_examples=100, deadline=None)
    @given(original_config=valid_agent_config(), data=st.data())
    @pytest.mark.asyncio
    async def test_config_cache_isolation(self, original_config, data):
        """
        Property: Configuration cache maintains isolation between versions.

        For any configuration reload, the cache should properly isolate
        different versions so that requests for old vs new configs
        return the correct version.
        """
        # Generate modified config
        modified_config = data.draw(modified_agent_config(original_config))

        assume(original_config["system_message"] != modified_config["system_message"])

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            agents_file = config_dir / "agents.json"

            # Write original config
            with open(agents_file, "w") as f:
                json.dump({"version": "1.0", "agents": [original_config]}, f)

            config_manager = ConfigurationManager(config_dir)

            # Load and cache original config
            agents_v1 = config_manager.load_agents_config(use_cache=False)
            agent_v1 = agents_v1.get_agent(original_config["id"])
            original_message = agent_v1.system_message

            # Load from cache - should get same config
            agents_v1_cached = config_manager.load_agents_config(use_cache=True)
            agent_v1_cached = agents_v1_cached.get_agent(original_config["id"])
            assert agent_v1_cached.system_message == original_message

            # Write modified config
            with open(agents_file, "w") as f:
                json.dump({"version": "1.0", "agents": [modified_config]}, f)

            # Load new config without cache
            agents_v2 = config_manager.load_agents_config(use_cache=False)
            agent_v2 = agents_v2.get_agent(modified_config["id"])
            new_message = agent_v2.system_message

            # New config should be different
            assert new_message == modified_config["system_message"]
            assert new_message != original_message

            # Old cached config should still be accessible if needed
            # (in practice, active sessions would hold references to old config)
            assert agent_v1.system_message == original_message
