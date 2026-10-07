"""
Property-based tests for CrewAI 0.4 configuration validation.

These tests verify correctness properties of configuration validation
using property-based testing with Hypothesis.

**Feature: crewai-native-migration, Property 25: Configuration Validation**
**Validates: Requirements 14.4**
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.config.agent_models import (
    AgentConfig,
    AgentType,
    LLMConfig,
    MemoryConfig,
    ModelClientConfig,
)
from src.config.workflow_models import (
    TeamConfig,
    TeamType,
    TerminationConfig,
    TerminationOperator,
    TerminationType,
)

# Strategies for generating valid configurations


@st.composite
def valid_agent_id(draw):
    """Generate a valid agent ID matching pattern ^[a-z0-9_]+$."""
    # First character must be lowercase letter
    first_char = draw(st.sampled_from("abcdefghijklmnopqrstuvwxyz"))
    # Remaining characters can be lowercase letters, digits, or underscores
    remaining = draw(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_", min_size=2, max_size=19)
    )
    return first_char + remaining


@st.composite
def valid_model_client_config(draw):
    """Generate a valid ModelClientConfig."""
    provider = draw(st.sampled_from(["openai", "azure", "openrouter"]))
    model = draw(st.sampled_from(["gpt-4", "gpt-3.5-turbo", "gpt-oss-20b"]))
    temperature = draw(st.floats(min_value=0.0, max_value=2.0))
    timeout = draw(st.integers(min_value=1, max_value=300))

    return ModelClientConfig(
        provider_id=provider,
        model=model,
        temperature=temperature,
        timeout=timeout,
    )


@st.composite
def valid_llm_config(draw):
    """Generate a valid LLMConfig."""
    provider = draw(st.sampled_from(["openai", "azure", "openrouter"]))
    model = draw(st.sampled_from(["gpt-4", "gpt-3.5-turbo", "google/gemma-3-27b-it"]))
    temperature = draw(st.floats(min_value=0.0, max_value=2.0))
    timeout = draw(st.integers(min_value=1, max_value=300))

    return LLMConfig(
        provider_id=provider,
        model=model,
        temperature=temperature,
        timeout=timeout,
    )


@st.composite
def valid_memory_config(draw):
    """Generate a valid MemoryConfig."""
    collection_name = draw(
        st.text(
            alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
            min_size=3,
            max_size=20,
        ).filter(lambda x: x and x[0].isalpha())
    )

    return MemoryConfig(
        type="rag",
        vector_db=draw(st.sampled_from(["chromadb", "qdrant", "pgvector"])),
        collection_name=collection_name,
        embedding_model="all-mpnet-base-v2",
    )


@st.composite
def valid_termination_config(draw):
    """Generate a valid TerminationConfig."""
    term_type = draw(st.sampled_from([TerminationType.TEXT_MENTION, TerminationType.MAX_MESSAGE]))

    if term_type == TerminationType.TEXT_MENTION:
        return TerminationConfig(
            type=term_type, text_mention=draw(st.sampled_from(["TERMINATE", "DONE", "END"]))
        )
    else:
        return TerminationConfig(
            type=term_type, max_messages=draw(st.integers(min_value=1, max_value=100))
        )


@st.composite
def valid_combined_termination_config(draw):
    """Generate a valid combined TerminationConfig."""
    conditions = [
        TerminationConfig(type=TerminationType.TEXT_MENTION, text_mention="TERMINATE"),
        TerminationConfig(
            type=TerminationType.MAX_MESSAGE,
            max_messages=draw(st.integers(min_value=1, max_value=100)),
        ),
    ]
    operator = draw(st.sampled_from([TerminationOperator.AND, TerminationOperator.OR]))

    return TerminationConfig(
        type=TerminationType.COMBINED,
        conditions=conditions,
        operator=operator,
    )


# **Feature: crewai-native-migration, Property 25: Configuration Validation**
# **Validates: Requirements 14.4**
@given(
    agent_id=valid_agent_id(),
    model_config=valid_model_client_config(),
)
@settings(max_examples=100, deadline=None)
def test_assistant_agent_with_model_client_config_is_v04_compatible(
    agent_id: str,
    model_config: ModelClientConfig,
):
    """
    *For any* assistant agent configuration with model_client_config,
    the validation function should report no v0.4 compatibility issues.
    """
    config = AgentConfig(
        id=agent_id,
        type=AgentType.ASSISTANT,
        name=f"Agent {agent_id}",
        model_client_config=model_config,
        system_message="You are a helpful assistant.",
    )

    errors = config.validate_v04_compatibility()
    assert len(errors) == 0, f"Expected no errors, got: {errors}"
    assert config.is_v04_compatible()


# **Feature: crewai-native-migration, Property 25: Configuration Validation**
# **Validates: Requirements 14.4**
@given(
    agent_id=valid_agent_id(),
)
@settings(max_examples=100, deadline=None)
def test_assistant_agent_without_model_config_reports_error(
    agent_id: str,
):
    """
    *For any* assistant agent configuration without model_client_config or llm_config,
    the validation function should report a compatibility error.
    """
    config = AgentConfig(
        id=agent_id,
        type=AgentType.ASSISTANT,
        name=f"Agent {agent_id}",
        system_message="You are a helpful assistant.",
    )

    errors = config.validate_v04_compatibility()
    assert len(errors) > 0, "Expected validation errors for assistant without model config"
    assert any("model_client_config" in err or "llm_config" in err for err in errors)
    assert not config.is_v04_compatible()


# **Feature: crewai-native-migration, Property 25: Configuration Validation**
# **Validates: Requirements 14.4**
@given(
    agent_id=valid_agent_id(),
    model_config=valid_model_client_config(),
    llm_config=valid_llm_config(),
)
@settings(max_examples=100, deadline=None)
def test_agent_with_both_configs_reports_error(
    agent_id: str,
    model_config: ModelClientConfig,
    llm_config: LLMConfig,
):
    """
    *For any* agent configuration with both llm_config and model_client_config,
    the validation function should report a compatibility error.
    """
    config = AgentConfig(
        id=agent_id,
        type=AgentType.ASSISTANT,
        name=f"Agent {agent_id}",
        model_client_config=model_config,
        llm_config=llm_config,
        system_message="You are a helpful assistant.",
    )

    errors = config.validate_v04_compatibility()
    assert len(errors) > 0, "Expected validation errors for agent with both configs"
    assert any("both" in err.lower() for err in errors)


# **Feature: crewai-native-migration, Property 25: Configuration Validation**
# **Validates: Requirements 14.4**
@given(
    agent_id=valid_agent_id(),
)
@settings(max_examples=100, deadline=None)
def test_code_executor_agent_without_execution_config_reports_error(
    agent_id: str,
):
    """
    *For any* code_executor agent configuration without code_execution_config,
    the validation function should report a compatibility error.
    """
    config = AgentConfig(
        id=agent_id,
        type=AgentType.CODE_EXECUTOR,
        name=f"Agent {agent_id}",
        code_execution_config=False,
    )

    errors = config.validate_v04_compatibility()
    assert len(errors) > 0, "Expected validation errors for code_executor without execution config"
    assert any("code_execution_config" in err for err in errors)


# **Feature: crewai-native-migration, Property 25: Configuration Validation**
# **Validates: Requirements 14.4**
@given(
    agent_id=valid_agent_id(),
)
@settings(max_examples=100, deadline=None)
def test_custom_agent_without_system_message_reports_error(
    agent_id: str,
):
    """
    *For any* custom agent configuration without system_message,
    the validation function should report a compatibility error.
    """
    config = AgentConfig(
        id=agent_id,
        type=AgentType.CUSTOM,
        name=f"Agent {agent_id}",
    )

    errors = config.validate_v04_compatibility()
    assert len(errors) > 0, "Expected validation errors for custom agent without system_message"
    assert any("system_message" in err for err in errors)


# **Feature: crewai-native-migration, Property 25: Configuration Validation**
# **Validates: Requirements 14.4**
@given(
    agent_id=valid_agent_id(),
    llm_config=valid_llm_config(),
)
@settings(max_examples=100, deadline=None)
def test_get_effective_model_config_converts_llm_config(
    agent_id: str,
    llm_config: LLMConfig,
):
    """
    *For any* agent with llm_config, get_effective_model_config should
    return a ModelClientConfig with equivalent settings.
    """
    config = AgentConfig(
        id=agent_id,
        type=AgentType.CONVERSABLE,
        name=f"Agent {agent_id}",
        llm_config=llm_config,
    )

    effective_config = config.get_effective_model_config()

    assert effective_config is not None
    assert effective_config.provider_id == llm_config.provider_id
    assert effective_config.model == llm_config.model
    assert effective_config.temperature == llm_config.temperature
    assert effective_config.timeout == llm_config.timeout


# **Feature: crewai-native-migration, Property 25: Configuration Validation**
# **Validates: Requirements 14.4**
@given(
    termination_config=valid_termination_config(),
)
@settings(max_examples=100, deadline=None)
def test_termination_config_validation(
    termination_config: TerminationConfig,
):
    """
    *For any* valid termination configuration, the configuration should
    be created without validation errors.
    """
    # If we got here, the config was created successfully
    assert termination_config.type in [TerminationType.TEXT_MENTION, TerminationType.MAX_MESSAGE]

    if termination_config.type == TerminationType.TEXT_MENTION:
        assert termination_config.text_mention is not None
    elif termination_config.type == TerminationType.MAX_MESSAGE:
        assert termination_config.max_messages is not None


# **Feature: crewai-native-migration, Property 25: Configuration Validation**
# **Validates: Requirements 14.4**
@given(
    termination_config=valid_combined_termination_config(),
)
@settings(max_examples=100, deadline=None)
def test_combined_termination_config_validation(
    termination_config: TerminationConfig,
):
    """
    *For any* valid combined termination configuration, the configuration
    should have at least 2 conditions and an operator.
    """
    assert termination_config.type == TerminationType.COMBINED
    assert termination_config.conditions is not None
    assert len(termination_config.conditions) >= 2
    assert termination_config.operator is not None


# **Feature: crewai-native-migration, Property 25: Configuration Validation**
# **Validates: Requirements 14.4**
@given(
    agent_ids=st.lists(valid_agent_id(), min_size=2, max_size=5, unique=True),
    termination_config=valid_termination_config(),
)
@settings(max_examples=100, deadline=None)
def test_team_config_validation(
    agent_ids: list,
    termination_config: TerminationConfig,
):
    """
    *For any* valid team configuration with at least 2 agents,
    the configuration should be created without validation errors.
    """
    team_config = TeamConfig(
        id="test_team",
        type=TeamType.ROUND_ROBIN,
        agents=agent_ids,
        termination_condition=termination_config,
    )

    assert team_config.type == TeamType.ROUND_ROBIN
    assert len(team_config.agents) >= 2
    assert team_config.termination_condition is not None


# **Feature: crewai-native-migration, Property 25: Configuration Validation**
# **Validates: Requirements 14.4**
def test_selector_team_requires_selector_config():
    """
    Test that selector team type requires selector configuration.
    """
    with pytest.raises(ValueError) as exc_info:
        TeamConfig(
            id="test_team",
            type=TeamType.SELECTOR,
            agents=["agent1", "agent2"],
            termination_condition=TerminationConfig(
                type=TerminationType.TEXT_MENTION, text_mention="TERMINATE"
            ),
        )

    assert "selector" in str(exc_info.value).lower()


# **Feature: crewai-native-migration, Property 25: Configuration Validation**
# **Validates: Requirements 14.4**
def test_termination_config_text_mention_requires_text():
    """
    Test that text_mention termination type requires text_mention field.
    """
    with pytest.raises(ValueError) as exc_info:
        TerminationConfig(
            type=TerminationType.TEXT_MENTION,
        )

    assert "text_mention" in str(exc_info.value).lower()


# **Feature: crewai-native-migration, Property 25: Configuration Validation**
# **Validates: Requirements 14.4**
def test_termination_config_max_message_requires_max_messages():
    """
    Test that max_message termination type requires max_messages field.
    """
    with pytest.raises(ValueError) as exc_info:
        TerminationConfig(
            type=TerminationType.MAX_MESSAGE,
        )

    assert "max_messages" in str(exc_info.value).lower()


# **Feature: crewai-native-migration, Property 25: Configuration Validation**
# **Validates: Requirements 14.4**
def test_termination_config_combined_requires_conditions():
    """
    Test that combined termination type requires conditions and operator.
    """
    with pytest.raises(ValueError) as exc_info:
        TerminationConfig(
            type=TerminationType.COMBINED,
            operator=TerminationOperator.AND,
        )

    assert "conditions" in str(exc_info.value).lower()
