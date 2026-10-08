"""Workflow registry for managing workflow configurations."""

import json
from pathlib import Path

from src.audit_logging import get_logger
from src.config.agent_models import AgentsConfig
from src.config.paths import config_path as default_path
from src.config.workflow_models import (
    ConversationPattern,
    WorkflowConfig,
    WorkflowsConfig,
)

logger = get_logger(__name__)


class WorkflowValidationError(Exception):
    """Exception raised when workflow validation fails."""

    pass


class WorkflowRegistry:
    """
    Registry for managing workflow configurations.

    This class handles:
    - Loading workflow configurations from JSON files
    - Validating workflow configurations
    - Checking agent references
    - Detecting circular dependencies
    - Providing access to workflow configurations
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        agents_config: AgentsConfig | None = None,
    ) -> None:
        """
        Initialize the workflow registry.

        Args:
            config_path: Path to workflows configuration file
            agents_config: Optional agents configuration for validation
        """
        self.config_path = (
            Path(config_path) if config_path is not None else default_path("workflows.json")
        )
        self.agents_config = agents_config
        self._workflows_config: WorkflowsConfig | None = None
        self._load_config()

    def _load_config(self) -> None:
        """
        Load workflow configuration from file.

        Raises:
            FileNotFoundError: If configuration file doesn't exist
            ValueError: If configuration is invalid
        """
        if not self.config_path.exists():
            logger.warning(
                "Workflow configuration file not found",
                path=str(self.config_path),
            )
            # Create empty configuration
            self._workflows_config = WorkflowsConfig(
                version="1.0.0",
                workflows=[],
            )
            return

        try:
            with open(self.config_path) as f:
                config_data = json.load(f)

            self._workflows_config = WorkflowsConfig(**config_data)

            logger.info(
                "Loaded workflow configuration",
                path=str(self.config_path),
                workflow_count=len(self._workflows_config.workflows),
            )

        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse workflow configuration",
                path=str(self.config_path),
                error=str(e),
            )
            raise ValueError(f"Invalid JSON in workflow configuration: {e}") from e
        except Exception as e:
            logger.error(
                "Failed to load workflow configuration",
                path=str(self.config_path),
                error=str(e),
            )
            raise

    def reload(self) -> None:
        """Reload workflow configuration from file."""
        logger.info("Reloading workflow configuration")
        self._load_config()

    def get_workflow(self, workflow_id: str) -> WorkflowConfig | None:
        """
        Get workflow configuration by ID.

        Args:
            workflow_id: Workflow identifier

        Returns:
            WorkflowConfig or None if not found
        """
        if self._workflows_config is None:
            return None
        return self._workflows_config.get_workflow(workflow_id)

    def list_workflows(self, enabled_only: bool = False) -> list[WorkflowConfig]:
        """
        List all workflow configurations.

        Args:
            enabled_only: If True, return only enabled workflows

        Returns:
            List of WorkflowConfig objects
        """
        if self._workflows_config is None:
            return []

        if enabled_only:
            return self._workflows_config.get_enabled_workflows()

        return self._workflows_config.workflows

    def validate_workflow(
        self,
        workflow: WorkflowConfig,
        check_agent_references: bool = True,
    ) -> None:
        """
        Validate a workflow configuration.

        Args:
            workflow: Workflow configuration to validate
            check_agent_references: Whether to validate agent references

        Raises:
            WorkflowValidationError: If validation fails
        """
        try:
            # Validate pattern-specific configuration
            workflow.validate_pattern_config()

            # Validate agent references if agents_config is available
            if check_agent_references and self.agents_config is not None:
                self._validate_agent_references(workflow)

            # Check for circular dependencies in sequential workflows
            if workflow.pattern == ConversationPattern.SEQUENTIAL:
                self._check_circular_dependencies(workflow)

            logger.debug(
                "Workflow validation passed",
                workflow_id=workflow.id,
            )

        except ValueError as e:
            raise WorkflowValidationError(f"Workflow validation failed: {e}") from e

    def validate_all(self, check_agent_references: bool = True) -> None:
        """
        Validate all workflow configurations.

        Args:
            check_agent_references: Whether to validate agent references

        Raises:
            WorkflowValidationError: If any validation fails
        """
        if self._workflows_config is None:
            return

        try:
            # Validate root configuration (checks for duplicate IDs)
            self._workflows_config.validate_all()

            # Validate each workflow
            for workflow in self._workflows_config.workflows:
                self.validate_workflow(
                    workflow,
                    check_agent_references=check_agent_references,
                )

            logger.info(
                "All workflows validated successfully",
                workflow_count=len(self._workflows_config.workflows),
            )

        except (ValueError, WorkflowValidationError) as e:
            logger.error("Workflow validation failed", error=str(e))
            raise WorkflowValidationError(str(e)) from e

    def _validate_agent_references(self, workflow: WorkflowConfig) -> None:
        """
        Validate that all agent references exist in agent configuration.

        Args:
            workflow: Workflow configuration to validate

        Raises:
            ValueError: If any agent reference is invalid
        """
        if self.agents_config is None:
            return

        # Get all agent IDs from the workflow
        agent_ids = workflow.get_all_agent_ids()

        # Check each agent ID exists
        for agent_id in agent_ids:
            agent_config = self.agents_config.get_agent(agent_id)
            if agent_config is None:
                raise ValueError(
                    f"Workflow {workflow.id}: Agent '{agent_id}' not found in agent configuration"
                )

        logger.debug(
            "Agent references validated",
            workflow_id=workflow.id,
            agent_count=len(agent_ids),
        )

    def _check_circular_dependencies(self, workflow: WorkflowConfig) -> None:
        """
        Check for circular dependencies in sequential workflow topologies.

        Detects immediate two-node cycles (A->B and B->A) and self-loop
        edges (A->A) in the topology graph, which would cause infinite loops
        in a sequential pipeline.

        Args:
            workflow: Workflow configuration to check

        Raises:
            ValueError: If circular dependencies are detected
        """
        if workflow.pattern != ConversationPattern.SEQUENTIAL:
            return

        edges = getattr(workflow.topology, "edges", None) or []
        edge_pairs = set()
        for edge in edges:
            source = getattr(edge, "source", None) or getattr(edge, "from_node", None)
            target = getattr(edge, "target", None) or getattr(edge, "to_node", None)
            if source is None or target is None:
                continue
            if source == target:
                raise ValueError(f"Workflow {workflow.id}: Self-loop detected on node '{source}'")
            if (target, source) in edge_pairs:
                raise ValueError(
                    f"Workflow {workflow.id}: Circular dependency detected between "
                    f"nodes '{source}' and '{target}'"
                )
            edge_pairs.add((source, target))

        logger.debug(
            "No circular dependencies found",
            workflow_id=workflow.id,
        )

    def set_agents_config(self, agents_config: AgentsConfig) -> None:
        """
        Set the agents configuration for validation.

        Args:
            agents_config: Agents configuration
        """
        self.agents_config = agents_config
        logger.debug("Updated agents configuration for workflow validation")

    def add_workflow(self, workflow: WorkflowConfig) -> None:
        """
        Add a new workflow configuration.

        Args:
            workflow: Workflow configuration to add

        Raises:
            WorkflowValidationError: If workflow is invalid or ID already exists
        """
        if self._workflows_config is None:
            self._workflows_config = WorkflowsConfig(
                version="1.0.0",
                workflows=[],
            )

        # Check if workflow ID already exists
        if self._workflows_config.get_workflow(workflow.id) is not None:
            raise WorkflowValidationError(f"Workflow with ID '{workflow.id}' already exists")

        # Validate the workflow
        self.validate_workflow(workflow)

        # Add to configuration
        self._workflows_config.workflows.append(workflow)

        logger.info("Added workflow", workflow_id=workflow.id)

    def update_workflow(self, workflow: WorkflowConfig) -> None:
        """
        Update an existing workflow configuration.

        Args:
            workflow: Workflow configuration to update

        Raises:
            WorkflowValidationError: If workflow is invalid or not found
        """
        if self._workflows_config is None:
            raise WorkflowValidationError("No workflows configuration loaded")

        # Find existing workflow
        existing_idx = None
        for i, w in enumerate(self._workflows_config.workflows):
            if w.id == workflow.id:
                existing_idx = i
                break

        if existing_idx is None:
            raise WorkflowValidationError(f"Workflow with ID '{workflow.id}' not found")

        # Validate the workflow
        self.validate_workflow(workflow)

        # Update configuration
        self._workflows_config.workflows[existing_idx] = workflow

        logger.info("Updated workflow", workflow_id=workflow.id)

    def remove_workflow(self, workflow_id: str) -> bool:
        """
        Remove a workflow configuration.

        Args:
            workflow_id: ID of workflow to remove

        Returns:
            True if removed, False if not found
        """
        if self._workflows_config is None:
            return False

        # Find and remove workflow
        for i, workflow in enumerate(self._workflows_config.workflows):
            if workflow.id == workflow_id:
                self._workflows_config.workflows.pop(i)
                logger.info("Removed workflow", workflow_id=workflow_id)
                return True

        return False

    def save_config(self) -> None:
        """
        Save current configuration to file.

        Raises:
            ValueError: If no configuration is loaded
        """
        if self._workflows_config is None:
            raise ValueError("No configuration to save")

        # Ensure directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert to dict and save
        config_dict = self._workflows_config.model_dump(mode="json", exclude_none=True)

        with open(self.config_path, "w") as f:
            json.dump(config_dict, f, indent=2)

        logger.info(
            "Saved workflow configuration",
            path=str(self.config_path),
            workflow_count=len(self._workflows_config.workflows),
        )


# Singleton instance
_workflow_registry: WorkflowRegistry | None = None


def get_workflow_registry() -> WorkflowRegistry:
    """
    Get the singleton workflow registry instance.

    Returns:
        WorkflowRegistry instance
    """
    global _workflow_registry
    if _workflow_registry is None:
        _workflow_registry = WorkflowRegistry()
        logger.info("Initialized workflow registry")
    return _workflow_registry


def set_workflow_registry(registry: WorkflowRegistry) -> None:
    """
    Set the singleton workflow registry instance.

    Args:
        registry: WorkflowRegistry instance to use
    """
    global _workflow_registry
    _workflow_registry = registry
    logger.info("Set workflow registry instance")
