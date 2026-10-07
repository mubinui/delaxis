"""Configuration validation utilities with versioning support."""

from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel

from src.config.agent_models import AgentConfig
from src.config.tool_models import ToolConfig
from src.config.vector_db_models import VectorDBConfig
from src.config.workflow_models import PersistenceMode, WorkflowConfig, WorkflowType

ConfigType = TypeVar("ConfigType", AgentConfig, ToolConfig, VectorDBConfig, WorkflowConfig)


class ConfigValidator:
    """Validator for configuration objects with versioning support."""

    @staticmethod
    def validate_workflow_type(workflow_type: str | WorkflowType) -> WorkflowType:
        """
        Validate workflow_type enum value.

        Args:
            workflow_type: Workflow type as string or enum

        Returns:
            WorkflowType enum value

        Raises:
            ValueError: If workflow_type is invalid
        """
        if isinstance(workflow_type, str):
            try:
                return WorkflowType(workflow_type)
            except ValueError as exc:
                valid_types = [t.value for t in WorkflowType]
                raise ValueError(
                    f"Invalid workflow_type '{workflow_type}'. "
                    f"Must be one of: {', '.join(valid_types)}"
                ) from exc
        return workflow_type

    @staticmethod
    def validate_persistence_mode(
        persistence: str | PersistenceMode, workflow_type: str | WorkflowType
    ) -> PersistenceMode:
        """
        Validate the persistence mode value.

        Args:
            persistence: Persistence mode as string or enum
            workflow_type: Workflow type as string or enum (kept for signature stability)

        Returns:
            PersistenceMode enum value

        Raises:
            ValueError: If persistence mode is invalid
        """
        # Convert to enum if string
        if isinstance(persistence, str):
            try:
                persistence = PersistenceMode(persistence)
            except ValueError as exc:
                valid_modes = [m.value for m in PersistenceMode]
                raise ValueError(
                    f"Invalid persistence mode '{persistence}'. "
                    f"Must be one of: {', '.join(valid_modes)}"
                ) from exc

        return persistence

    @staticmethod
    def increment_version(config: ConfigType) -> ConfigType:
        """
        Increment the version number of a configuration object.

        Args:
            config: Configuration object with version field

        Returns:
            Updated configuration object with incremented version
        """
        if hasattr(config, "version"):
            config.version += 1
        return config

    @staticmethod
    def update_timestamp(config: ConfigType) -> ConfigType:
        """
        Update the last_updated timestamp of a configuration object.

        Args:
            config: Configuration object with last_updated field

        Returns:
            Updated configuration object with current timestamp
        """
        if hasattr(config, "last_updated"):
            config.last_updated = datetime.now(UTC)
        return config

    @staticmethod
    def prepare_for_update(config: ConfigType) -> ConfigType:
        """
        Prepare a configuration object for update by incrementing version and updating timestamp.

        Args:
            config: Configuration object to prepare

        Returns:
            Updated configuration object
        """
        config = ConfigValidator.increment_version(config)
        config = ConfigValidator.update_timestamp(config)
        return config

    @staticmethod
    def validate_workflow_config(config: WorkflowConfig) -> None:
        """
        Validate a workflow configuration including pattern-specific requirements.

        Args:
            config: Workflow configuration to validate

        Raises:
            ValueError: If configuration is invalid
        """
        # Validate workflow type
        config.workflow_type = ConfigValidator.validate_workflow_type(config.workflow_type)

        # Validate persistence mode
        config.persistence = ConfigValidator.validate_persistence_mode(
            config.persistence, config.workflow_type
        )

        # Validate pattern-specific configuration
        config.validate_pattern_config()

    @staticmethod
    def validate_agent_config(config: AgentConfig) -> None:
        """
        Validate an agent configuration.

        Args:
            config: Agent configuration to validate

        Raises:
            ValueError: If configuration is invalid
        """
        config.validate_config()

        # Validate behavior configuration if present
        if config.behavior:
            # Ensure behavior configuration is valid
            # The Pydantic model already validates structure
            # Additional validation can be added here if needed
            pass

    @staticmethod
    def validate_tool_config(config: ToolConfig) -> None:
        """
        Validate a tool configuration.

        Args:
            config: Tool configuration to validate

        Raises:
            ValueError: If configuration is invalid
        """
        config.validate_entrypoint()

    @staticmethod
    def validate_vector_db_config(config: VectorDBConfig) -> None:
        """
        Validate a vector database configuration.

        Args:
            config: Vector database configuration to validate

        Raises:
            ValueError: If configuration is invalid
        """
        config.validate_config()


class VersionManager:
    """Manager for configuration versioning operations."""

    @staticmethod
    def create_version_metadata(config: BaseModel, updated_by: str = "system") -> dict[str, Any]:
        """
        Create version metadata for a configuration.

        Args:
            config: Configuration object
            updated_by: User or system that updated the configuration

        Returns:
            Dictionary with version metadata
        """
        return {
            "version": getattr(config, "version", 1),
            "last_updated": getattr(config, "last_updated", datetime.now(UTC)).isoformat(),
            "updated_by": updated_by,
        }

    @staticmethod
    def compare_versions(config1: BaseModel, config2: BaseModel) -> dict[str, Any]:
        """
        Compare two configuration versions and return differences.

        Args:
            config1: First configuration (older)
            config2: Second configuration (newer)

        Returns:
            Dictionary with added, removed, and modified fields
        """
        dict1 = config1.model_dump() if hasattr(config1, "model_dump") else config1.dict()
        dict2 = config2.model_dump() if hasattr(config2, "model_dump") else config2.dict()

        added = []
        removed = []
        modified = []

        # Find added and modified fields
        for key, value2 in dict2.items():
            if key not in dict1:
                added.append(key)
            elif dict1[key] != value2:
                modified.append({"field": key, "old_value": dict1[key], "new_value": value2})

        # Find removed fields
        for key in dict1:
            if key not in dict2:
                removed.append(key)

        return {"added": added, "removed": removed, "modified": modified}
