"""
Property-based tests for invalid configuration rejection.

**Feature: industry-grade-orchestration, Property 20: Invalid configuration rejection**
**Validates: Requirements 8.2**
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.config.agent_models import AgentType, HumanInputMode
from src.config.config_manager import ConfigurationError, ConfigurationManager
from src.config.execution_models import BackoffStrategy, ExecutionMode


@st.composite
def valid_execution_config(draw):
    """Generate valid execution configuration."""
    return {
        "max_workers": draw(st.integers(min_value=1, max_value=100)),
        "queue_size": draw(st.integers(min_value=1, max_value=1000)),
        "default_timeout": draw(st.floats(min_value=1.0, max_value=3600.0)),
        "enable_parallel": draw(st.booleans()),
        "execution_mode": draw(st.sampled_from([mode.value for mode in ExecutionMode])),
        "retry_strategy": {
            "max_retries": draw(st.integers(min_value=0, max_value=10)),
            "backoff_factor": draw(st.floats(min_value=1.0, max_value=10.0)),
            "backoff_strategy": draw(st.sampled_from([s.value for s in BackoffStrategy])),
            "retry_on": ["timeout", "rate_limit"],
            "dont_retry_on": ["validation_error"],
        },
    }


@st.composite
def invalid_execution_config(draw):
    """Generate invalid execution configuration."""
    config = draw(valid_execution_config())

    # Introduce an invalid field
    invalid_choice = draw(st.integers(min_value=0, max_value=3))

    if invalid_choice == 0:
        # Invalid max_workers (negative or zero)
        config["max_workers"] = draw(st.integers(max_value=0))
    elif invalid_choice == 1:
        # Invalid queue_size (negative or zero)
        config["queue_size"] = draw(st.integers(max_value=0))
    elif invalid_choice == 2:
        # Invalid default_timeout (negative or zero)
        config["default_timeout"] = draw(st.floats(max_value=0.0))
    else:
        # Invalid execution_mode
        config["execution_mode"] = draw(
            st.text(min_size=1, max_size=20).filter(
                lambda x: x not in [mode.value for mode in ExecutionMode]
            )
        )

    return config


class TestInvalidConfigurationRejection:
    """
    Property 20: Invalid configuration rejection

    For any invalid configuration change, the system should reject the change,
    maintain the previous valid configuration, and continue operating normally.

    Validates: Requirements 8.2
    """

    @settings(max_examples=100)
    @given(invalid_config=invalid_execution_config())
    def test_invalid_execution_config_rejected(self, invalid_config):
        """
        Property: Invalid execution configurations should be rejected.

        For any execution configuration with invalid values,
        validation should fail and the error should be reported.
        """
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "execution.json"

            # Write invalid config
            with open(config_file, "w") as f:
                json.dump(invalid_config, f)

            manager = ConfigurationManager(config_dir)

            # Loading should fail
            with pytest.raises(ConfigurationError):
                manager.load_execution_config(use_cache=False)

    @settings(max_examples=100)
    @given(valid_config=valid_execution_config(), invalid_config=invalid_execution_config())
    def test_invalid_config_preserves_previous_valid(self, valid_config, invalid_config):
        """
        Property: When invalid config is loaded, previous valid config is preserved.

        For any valid configuration followed by an invalid configuration,
        the system should reject the invalid config and maintain the valid one.
        """
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "execution.json"

            # Write and load valid config
            with open(config_file, "w") as f:
                json.dump(valid_config, f)

            manager = ConfigurationManager(config_dir)
            valid_loaded = manager.load_execution_config(use_cache=False)

            # Verify valid config loaded
            assert valid_loaded.max_workers == valid_config["max_workers"]

            # Write invalid config
            with open(config_file, "w") as f:
                json.dump(invalid_config, f)

            # Try to reload - should fail
            with pytest.raises(ConfigurationError):
                manager.load_execution_config(use_cache=False)

            # Previous valid config should still be in cache
            cached_config = manager.load_execution_config(use_cache=True)
            assert cached_config.max_workers == valid_config["max_workers"]

    @settings(max_examples=100)
    @given(data=st.data())
    def test_invalid_agents_config_rejected(self, data):
        """Generate valid agent ID."""
        length = data.draw(st.integers(min_value=3, max_value=20))
        first_char = data.draw(st.sampled_from("abcdefghijklmnopqrstuvwxyz"))
        rest_chars = data.draw(
            st.lists(
                st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_"),
                min_size=length - 1,
                max_size=length - 1,
            )
        )
        agent_id = first_char + "".join(rest_chars)
        """
        Property: Invalid agents configurations should be rejected.

        For any agents configuration with validation errors,
        the configuration should be rejected with detailed error messages.
        """
        # Create invalid config - two agents sharing the same id
        agent_entry = {
            "id": agent_id,
            "type": AgentType.CONVERSABLE.value,
            "name": "Test Agent",
            "system_message": "Test message",
            "human_input_mode": HumanInputMode.NEVER.value,
            "max_consecutive_auto_reply": 10,
        }
        invalid_config = {
            "version": "1.0",
            "agents": [agent_entry, dict(agent_entry)],
        }

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "agents.json"

            # Write invalid config
            with open(config_file, "w") as f:
                json.dump(invalid_config, f)

            manager = ConfigurationManager(config_dir)

            # Loading should fail
            with pytest.raises(ConfigurationError) as exc_info:
                manager.load_agents_config(use_cache=False)

            # Error message should be informative
            error_msg = str(exc_info.value)
            assert len(error_msg) > 0
            assert "duplicate" in error_msg.lower()

    @settings(max_examples=100)
    @given(config_data=invalid_execution_config())
    def test_validation_provides_detailed_errors(self, config_data):
        """
        Property: Validation should provide detailed error messages.

        For any invalid configuration, the validation result should contain
        specific error messages indicating what is wrong.
        """
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            manager = ConfigurationManager(config_dir)

            # Validate execution config
            result = manager.validate_config("execution", config_data)

            # Should be invalid
            assert not result.valid

            # Should have error messages
            assert len(result.errors) > 0

            # Error messages should be non-empty strings
            for error in result.errors:
                assert isinstance(error, str)
                assert len(error) > 0

    @settings(max_examples=100)
    @given(valid_config=valid_execution_config())
    def test_valid_config_accepted(self, valid_config):
        """
        Property: Valid configurations should be accepted.

        For any valid configuration, validation should succeed
        and the configuration should be loaded successfully.
        """
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "execution.json"

            # Write valid config
            with open(config_file, "w") as f:
                json.dump(valid_config, f)

            manager = ConfigurationManager(config_dir)

            # Loading should succeed
            loaded = manager.load_execution_config(use_cache=False)

            # Values should match
            assert loaded.max_workers == valid_config["max_workers"]
            assert loaded.queue_size == valid_config["queue_size"]
            assert loaded.enable_parallel == valid_config["enable_parallel"]

    @settings(max_examples=100)
    @given(
        malformed_json=st.text(min_size=1, max_size=100).filter(
            lambda x: (
                x.strip()
                and not x.strip().startswith("{")
                and not x.strip().startswith("[")
                and x.strip() not in ["true", "false", "null"]
                and not x.strip().replace(".", "").replace("-", "").isdigit()
            )
        )
    )
    def test_malformed_json_rejected(self, malformed_json):
        """
        Property: Malformed JSON should be rejected.

        For any non-object JSON content or malformed JSON, loading should fail with
        a clear error indicating the JSON is invalid or the data is wrong type.
        """
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_file = config_dir / "execution.json"

            # Write malformed JSON
            with open(config_file, "w") as f:
                f.write(malformed_json)

            manager = ConfigurationManager(config_dir)

            # Loading should fail
            with pytest.raises(ConfigurationError):
                manager.load_execution_config(use_cache=False)
