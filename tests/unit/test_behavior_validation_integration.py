"""
Integration tests for agent behavior validation.

Tests the complete flow of creating agents with behavior configuration
and validating their outputs.
"""

from src.config.agent_models import AgentConfig, AgentType, LLMConfig
from src.config.behavior_models import (
    AgentBehaviorConfig,
    ConstraintsConfig,
    OutputFormatConfig,
    OutputFormatType,
    SecurityConfig,
)
from src.config.behavior_validator import AgentBehaviorValidator


class TestBehaviorValidationIntegration:
    """Integration tests for behavior validation."""

    def test_agent_with_json_output_format(self):
        """Test creating an agent with JSON output format validation."""
        # Create behavior config
        behavior = AgentBehaviorConfig(output_format=OutputFormatConfig(type=OutputFormatType.JSON))

        # Create agent config
        agent_config = AgentConfig(
            id="test_json_agent",
            type=AgentType.CONVERSABLE,
            name="TestJSONAgent",
            system_message="You are a test agent that outputs JSON",
            llm_config=LLMConfig(provider_id="test_provider", model="test-model"),
            behavior=behavior,
        )

        # Validate config
        agent_config.validate_config()

        # Verify behavior is set
        assert agent_config.behavior is not None
        assert agent_config.behavior.output_format is not None
        assert agent_config.behavior.output_format.type == OutputFormatType.JSON

    def test_agent_with_code_constraints(self):
        """Test creating an agent with code output constraints."""
        # Create behavior config
        behavior = AgentBehaviorConfig(
            output_format=OutputFormatConfig(type=OutputFormatType.CODE, language="python"),
            constraints=ConstraintsConfig(
                require_language_specification=True, forbidden_patterns=[r"eval\(", r"exec\("]
            ),
            validation=SecurityConfig(syntax_check=True, security_scan=True),
        )

        # Create agent config
        agent_config = AgentConfig(
            id="test_code_agent",
            type=AgentType.CONVERSABLE,
            name="TestCodeAgent",
            system_message="You are a code generation agent",
            llm_config=LLMConfig(provider_id="test_provider", model="test-model"),
            behavior=behavior,
        )

        # Validate config
        agent_config.validate_config()

        # Verify behavior is set
        assert agent_config.behavior is not None
        assert agent_config.behavior.output_format.type == OutputFormatType.CODE
        assert agent_config.behavior.constraints.require_language_specification
        assert agent_config.behavior.validation.syntax_check

    def test_validator_with_multiple_constraints(self):
        """Test validator with multiple constraints."""
        # Create behavior config with multiple constraints
        behavior = AgentBehaviorConfig(
            constraints=ConstraintsConfig(
                max_output_length=100,
                min_output_length=10,
                forbidden_patterns=["bad_word"],
                required_patterns=["REQUIRED"],
            )
        )

        validator = AgentBehaviorValidator(behavior)

        # Test valid output
        valid_output = "This is a valid output with REQUIRED keyword"
        result = validator.validate(valid_output)
        assert result.valid

        # Test output too short
        short_output = "Short"
        result = validator.validate(short_output)
        assert not result.valid
        assert any("length" in err.lower() for err in result.errors)

        # Test output too long
        long_output = "x" * 150
        result = validator.validate(long_output)
        assert not result.valid
        assert any("length" in err.lower() or "exceeds" in err.lower() for err in result.errors)

        # Test forbidden pattern
        forbidden_output = "This contains bad_word which is forbidden REQUIRED"
        result = validator.validate(forbidden_output)
        assert not result.valid
        assert any("forbidden" in err.lower() for err in result.errors)

        # Test missing required pattern (case-sensitive)
        missing_required = "This output is missing the keyword"  # Missing "REQUIRED"
        result = validator.validate(missing_required)
        assert not result.valid, f"Expected validation to fail but got: {result.errors}"
        assert any("required" in err.lower() or "missing" in err.lower() for err in result.errors)

    def test_agent_config_with_behavior_validation(self):
        """Test that agent config properly stores behavior configuration."""
        # Create agent config with behavior
        behavior = AgentBehaviorConfig(
            output_format=OutputFormatConfig(type=OutputFormatType.JSON),
            constraints=ConstraintsConfig(max_output_length=1000),
        )

        agent_config = AgentConfig(
            id="test_agent",
            type=AgentType.CONVERSABLE,
            name="TestAgent",
            system_message="Test agent",
            llm_config=LLMConfig(provider_id="test_provider", model="test-model"),
            behavior=behavior,
        )

        # Verify behavior is properly stored
        assert agent_config.behavior is not None
        assert agent_config.behavior.output_format is not None
        assert agent_config.behavior.output_format.type == OutputFormatType.JSON
        assert agent_config.behavior.constraints is not None
        assert agent_config.behavior.constraints.max_output_length == 1000
        assert agent_config.behavior.has_validation()

    def test_behavior_config_has_validation_method(self):
        """Test that behavior config correctly reports if validation is configured."""
        # Default config has response-quality validation enabled
        behavior = AgentBehaviorConfig()
        assert behavior.has_validation()

        # No validation when quality checks are explicitly disabled
        behavior = AgentBehaviorConfig(validate_response_quality=False)
        assert not behavior.has_validation()

        # With output format
        behavior = AgentBehaviorConfig(output_format=OutputFormatConfig(type=OutputFormatType.JSON))
        assert behavior.has_validation()

        # With constraints
        behavior = AgentBehaviorConfig(constraints=ConstraintsConfig(max_output_length=100))
        assert behavior.has_validation()

        # With security validation
        behavior = AgentBehaviorConfig(validation=SecurityConfig(syntax_check=True))
        assert behavior.has_validation()
