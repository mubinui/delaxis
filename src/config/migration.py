"""
Configuration migration utilities for CrewAI 0.2 to 0.4.

This module provides utilities for converting v0.2 configurations to v0.4 format,
enabling smooth migration from CrewAI 0.2 to CrewAI 0.4.

Based on the design document specification for Requirements 14.5.
"""

from typing import Any

from src.audit_logging import get_logger
from src.config.agent_models import (
    AgentConfig,
    AgentType,
    LLMConfig,
    MemoryConfig,
    ModelClientConfig,
    RetrieveConfig,
)
from src.config.workflow_models import (
    GroupChatConfig,
    SpeakerSelectionMethod,
    TeamConfig,
    TeamType,
    TerminationConfig,
    TerminationType,
)

logger = get_logger(__name__)


class ConfigurationMigrationError(Exception):
    """Raised when configuration migration fails."""

    pass


def convert_llm_config_to_model_client_config(
    llm_config: LLMConfig,
) -> ModelClientConfig:
    """Convert v0.2 LLMConfig to v0.4 ModelClientConfig.

    Args:
        llm_config: v0.2 LLM configuration

    Returns:
        v0.4 ModelClientConfig
    """
    return ModelClientConfig(
        provider_id=llm_config.provider_id,
        model=llm_config.model,
        temperature=llm_config.temperature,
        timeout=llm_config.timeout,
        max_tokens=llm_config.max_tokens,
        seed=llm_config.cache_seed,
    )


def convert_retrieve_config_to_memory_config(
    retrieve_config: RetrieveConfig,
) -> MemoryConfig:
    """Convert v0.2 RetrieveConfig to v0.4 MemoryConfig.

    Args:
        retrieve_config: v0.2 retrieval configuration

    Returns:
        v0.4 MemoryConfig
    """
    return MemoryConfig(
        type="rag",
        vector_db=retrieve_config.vector_db,
        collection_name=retrieve_config.collection_name,
        embedding_model=retrieve_config.embedding_model,
        docs_path=retrieve_config.docs_path,
        chunk_token_size=retrieve_config.chunk_token_size,
        db_config=retrieve_config.db_config,
    )


def convert_agent_type_v02_to_v04(
    agent_type: AgentType,
    has_code_execution: bool = False,
) -> AgentType:
    """Convert v0.2 agent type to v0.4 agent type.

    Args:
        agent_type: v0.2 agent type
        has_code_execution: Whether the agent has code execution enabled

    Returns:
        v0.4 agent type
    """
    type_mapping = {
        AgentType.CONVERSABLE: AgentType.ASSISTANT,
        AgentType.RETRIEVE_USER_PROXY: AgentType.ASSISTANT,  # RAG agents become assistants with memory
        AgentType.GROUP_CHAT_MANAGER: AgentType.ASSISTANT,  # Managers become assistants in teams
    }

    # Code execution agents become code_executor type
    if has_code_execution:
        return AgentType.CODE_EXECUTOR

    return type_mapping.get(agent_type, AgentType.ASSISTANT)


def convert_agent_config_v02_to_v04(
    agent_config: AgentConfig,
) -> tuple[AgentConfig, list[str]]:
    """Convert v0.2 AgentConfig to v0.4 compatible format.

    This function converts a v0.2 agent configuration to v0.4 format,
    handling llm_config to model_client_config conversion and
    retrieve_config to memory_config conversion.

    Args:
        agent_config: v0.2 agent configuration

    Returns:
        Tuple of (converted AgentConfig, list of warnings)
    """
    warnings: list[str] = []

    # Determine if code execution is enabled
    has_code_execution = (
        agent_config.code_execution_config is not None
        and agent_config.code_execution_config is not False
    )

    # Convert agent type
    new_type = convert_agent_type_v02_to_v04(agent_config.type, has_code_execution)

    # Convert LLM config to model client config
    model_client_config = None
    if agent_config.llm_config is not None and agent_config.llm_config is not False:
        model_client_config = convert_llm_config_to_model_client_config(agent_config.llm_config)
        warnings.append(f"Agent {agent_config.id}: Converted llm_config to model_client_config")

    # Convert retrieve config to memory config
    memory_config = None
    if agent_config.retrieve_config is not None:
        memory_config = convert_retrieve_config_to_memory_config(agent_config.retrieve_config)
        warnings.append(f"Agent {agent_config.id}: Converted retrieve_config to memory_config")

    # Log type conversion
    if new_type != agent_config.type:
        warnings.append(
            f"Agent {agent_config.id}: Converted type from {agent_config.type.value} to {new_type.value}"
        )

    # Create new config with v0.4 fields
    new_config = AgentConfig(
        id=agent_config.id,
        type=new_type,
        name=agent_config.name,
        system_message=agent_config.system_message,
        llm_config=None,  # Clear v0.2 config
        model_client_config=model_client_config,
        memory_config=memory_config,
        reflect_on_tool_use=True,  # Default for v0.4
        human_input_mode=agent_config.human_input_mode,
        code_execution_config=agent_config.code_execution_config,
        tools=agent_config.tools,
        max_consecutive_auto_reply=agent_config.max_consecutive_auto_reply,
        retrieve_config=None,  # Clear v0.2 config
        description=agent_config.description,
        behavior=agent_config.behavior,
        version=agent_config.version + 1,  # Increment version
    )

    return new_config, warnings


def convert_group_chat_to_team_config(
    group_chat_config: GroupChatConfig,
    team_id: str,
    max_turns: int | None = None,
    llm_config: LLMConfig | None = None,
) -> tuple[TeamConfig, list[str]]:
    """Convert v0.2 GroupChatConfig to v0.4 TeamConfig.

    Args:
        group_chat_config: v0.2 group chat configuration
        team_id: ID for the new team
        max_turns: Maximum turns (optional)
        llm_config: LLM config for selector teams (optional)

    Returns:
        Tuple of (TeamConfig, list of warnings)
    """
    warnings: list[str] = []

    # Determine team type based on speaker selection method
    # Note: SELECTOR team type requires selector_model_client_config or selector_func
    # If no llm_config is provided, we fall back to ROUND_ROBIN
    if group_chat_config.speaker_selection_method == SpeakerSelectionMethod.ROUND_ROBIN:
        team_type = TeamType.ROUND_ROBIN
    elif group_chat_config.speaker_selection_method in (
        SpeakerSelectionMethod.AUTO,
        SpeakerSelectionMethod.MANUAL,
    ):
        # Only use SELECTOR if we have an llm_config to configure it
        if llm_config is not None:
            team_type = TeamType.SELECTOR
            warnings.append(
                f"Team {team_id}: Converted speaker_selection_method "
                f"{group_chat_config.speaker_selection_method.value} to selector team"
            )
        else:
            # Fall back to ROUND_ROBIN if no llm_config provided
            team_type = TeamType.ROUND_ROBIN
            warnings.append(
                f"Team {team_id}: speaker_selection_method "
                f"{group_chat_config.speaker_selection_method.value} requires llm_config for selector team, "
                "falling back to round_robin"
            )
    else:
        team_type = TeamType.ROUND_ROBIN
        warnings.append(
            f"Team {team_id}: Unknown speaker_selection_method "
            f"{group_chat_config.speaker_selection_method.value}, defaulting to round_robin"
        )

    # Create termination condition from max_round
    termination_condition = TerminationConfig(
        type=TerminationType.MAX_MESSAGE,
        max_messages=group_chat_config.max_round,
    )

    # Convert selector model client config if needed
    selector_model_client_config = None
    if team_type == TeamType.SELECTOR and llm_config is not None:
        selector_model_client_config = convert_llm_config_to_model_client_config(
            llm_config
        ).model_dump()

    team_config = TeamConfig(
        id=team_id,
        type=team_type,
        agents=group_chat_config.agents,
        termination_condition=termination_condition,
        max_turns=max_turns or group_chat_config.max_round,
        selector_model_client_config=selector_model_client_config,
    )

    return team_config, warnings


def convert_v02_to_v04(
    config: dict[str, Any],
    config_type: str = "agent",
) -> tuple[dict[str, Any], list[str]]:
    """Convert a v0.2 configuration dictionary to v0.4 format.

    This is the main entry point for configuration migration.

    Args:
        config: v0.2 configuration dictionary
        config_type: Type of configuration ("agent", "workflow", "tool")

    Returns:
        Tuple of (converted configuration dict, list of warnings)

    Raises:
        ConfigurationMigrationError: If migration fails
    """
    warnings: list[str] = []

    try:
        if config_type == "agent":
            # Parse as AgentConfig
            agent_config = AgentConfig(**config)
            new_config, agent_warnings = convert_agent_config_v02_to_v04(agent_config)
            warnings.extend(agent_warnings)
            return new_config.model_dump(exclude_none=True), warnings

        elif config_type == "workflow":
            # Workflow migration is more complex - handle group_chat conversion
            result = dict(config)

            if "group_chat" in config and config.get("group_chat"):
                group_chat_config = GroupChatConfig(**config["group_chat"])
                team_config, team_warnings = convert_group_chat_to_team_config(
                    group_chat_config,
                    team_id=f"{config.get('id', 'unknown')}_team",
                )
                warnings.extend(team_warnings)
                result["team_config"] = team_config.model_dump(exclude_none=True)
                warnings.append(
                    f"Workflow {config.get('id', 'unknown')}: Added team_config from group_chat"
                )

            return result, warnings

        elif config_type == "tool":
            # Tool migration - add is_async field if not present
            result = dict(config)
            if "is_async" not in result:
                result["is_async"] = False
                warnings.append(
                    f"Tool {config.get('id', 'unknown')}: Added is_async=False (default)"
                )
            return result, warnings

        else:
            raise ConfigurationMigrationError(f"Unknown configuration type: {config_type}")

    except Exception as e:
        raise ConfigurationMigrationError(
            f"Failed to migrate {config_type} configuration: {str(e)}"
        ) from e


def migrate_agent_configs(
    agents: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Migrate a list of agent configurations from v0.2 to v0.4.

    Args:
        agents: List of v0.2 agent configuration dictionaries

    Returns:
        Tuple of (list of converted configs, list of all warnings)
    """
    all_warnings: list[str] = []
    converted_agents: list[dict[str, Any]] = []

    for agent in agents:
        try:
            converted, warnings = convert_v02_to_v04(agent, config_type="agent")
            converted_agents.append(converted)
            all_warnings.extend(warnings)
        except ConfigurationMigrationError as e:
            all_warnings.append(f"Failed to migrate agent: {str(e)}")
            # Keep original config if migration fails
            converted_agents.append(agent)

    return converted_agents, all_warnings


def validate_migration(
    original: dict[str, Any],
    migrated: dict[str, Any],
    config_type: str = "agent",
) -> list[str]:
    """Validate that a migration preserved essential configuration.

    Args:
        original: Original v0.2 configuration
        migrated: Migrated v0.4 configuration
        config_type: Type of configuration

    Returns:
        List of validation errors (empty if valid)
    """
    errors: list[str] = []

    if config_type == "agent":
        # Check that essential fields are preserved
        if original.get("id") != migrated.get("id"):
            errors.append("Agent ID was not preserved")

        if original.get("name") != migrated.get("name"):
            errors.append("Agent name was not preserved")

        if original.get("system_message") != migrated.get("system_message"):
            errors.append("System message was not preserved")

        if original.get("tools") != migrated.get("tools"):
            errors.append("Tools list was not preserved")

        # Check that model configuration was converted
        if original.get("llm_config") and not migrated.get("model_client_config"):
            errors.append("LLM config was not converted to model_client_config")

        # Check that retrieve config was converted
        if original.get("retrieve_config") and not migrated.get("memory_config"):
            errors.append("Retrieve config was not converted to memory_config")

    return errors
