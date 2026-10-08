"""Dependency validation for configuration management."""

from pathlib import Path

from src.audit_logging import get_logger
from src.config.loader import ConfigurationLoader
from src.config.paths import config_path

logger = get_logger(__name__)


class DependencyError(Exception):
    """Raised when dependency validation fails."""

    def __init__(
        self,
        message: str,
        missing: list[str] | None = None,
        available: list[str] | None = None,
        dependents: list[str] | None = None,
    ) -> None:
        """
        Initialize dependency error.

        Args:
            message: Error message
            missing: List of missing dependencies
            available: List of available dependencies
            dependents: List of entities that depend on the target
        """
        super().__init__(message)
        self.missing = missing or []
        self.available = available or []
        self.dependents = dependents or []


class DependencyValidator:
    """Validates dependencies between configuration entities."""

    def __init__(self, config_loader: ConfigurationLoader | None = None) -> None:
        """
        Initialize dependency validator.

        Args:
            config_loader: Configuration loader instance
        """
        self.config_loader = config_loader or ConfigurationLoader()

    def validate_agent_tool_references(self, agent_id: str, tool_ids: list[str]) -> None:
        """
        Validate that all tool references in an agent configuration exist.

        Args:
            agent_id: Agent identifier
            tool_ids: List of tool IDs referenced by the agent

        Raises:
            DependencyError: If any tool references are invalid

        Requirements: 5.3, 8.2
        """
        if not tool_ids:
            return

        # Load tools configuration
        tools_config = self.config_loader.load_tools()
        available_tool_ids = {tool.id for tool in tools_config.tools}

        # Check for missing tools
        missing_tools = [tid for tid in tool_ids if tid not in available_tool_ids]

        if missing_tools:
            logger.warning(
                "Agent references missing tools",
                agent_id=agent_id,
                missing_tools=missing_tools,
                available_tools=list(available_tool_ids),
            )
            raise DependencyError(
                f"Agent '{agent_id}' references tools that do not exist: {', '.join(missing_tools)}",
                missing=missing_tools,
                available=list(available_tool_ids),
            )

        logger.debug(
            "Agent tool references validated",
            agent_id=agent_id,
            tool_count=len(tool_ids),
        )

    def validate_workflow_agent_references(self, workflow_id: str, agent_ids: set[str]) -> None:
        """
        Validate that all agent references in a workflow configuration exist.

        Args:
            workflow_id: Workflow identifier
            agent_ids: Set of agent IDs referenced by the workflow

        Raises:
            DependencyError: If any agent references are invalid

        Requirements: 6.4, 8.3
        """
        if not agent_ids:
            return

        # Load agents configuration
        import json

        from src.config.agent_models import AgentsConfig

        # Use config_loader's directory if available
        if hasattr(self.config_loader, "config_dir"):
            agents_path = Path(self.config_loader.config_dir) / "agents.json"
        else:
            agents_path = config_path("agents.json")

        if not agents_path.exists():
            raise DependencyError(
                f"Workflow '{workflow_id}' references agents but agents configuration not found",
                missing=list(agent_ids),
                available=[],
            )

        with open(agents_path) as f:
            agents_data = json.load(f)

        agents_config = AgentsConfig(**agents_data)
        available_agent_ids = {agent.id for agent in agents_config.agents}

        # Check for missing agents
        missing_agents = [aid for aid in agent_ids if aid not in available_agent_ids]

        if missing_agents:
            logger.warning(
                "Workflow references missing agents",
                workflow_id=workflow_id,
                missing_agents=missing_agents,
                available_agents=list(available_agent_ids),
            )
            raise DependencyError(
                f"Workflow '{workflow_id}' references agents that do not exist: {', '.join(missing_agents)}",
                missing=missing_agents,
                available=list(available_agent_ids),
            )

        logger.debug(
            "Workflow agent references validated",
            workflow_id=workflow_id,
            agent_count=len(agent_ids),
        )

    def check_tool_dependencies(self, tool_id: str) -> list[str]:
        """
        Check which agents depend on a specific tool.

        Args:
            tool_id: Tool identifier

        Returns:
            List of agent IDs that reference this tool

        Requirements: 3.5, 8.2
        """
        import json

        from src.config.agent_models import AgentsConfig

        # Use config_loader's directory if available
        if hasattr(self.config_loader, "config_dir"):
            agents_path = Path(self.config_loader.config_dir) / "agents.json"
        else:
            agents_path = config_path("agents.json")

        if not agents_path.exists():
            return []

        with open(agents_path) as f:
            agents_data = json.load(f)

        agents_config = AgentsConfig(**agents_data)

        # Find agents that reference this tool
        dependent_agents = [agent.id for agent in agents_config.agents if tool_id in agent.tools]

        logger.debug(
            "Checked tool dependencies",
            tool_id=tool_id,
            dependent_count=len(dependent_agents),
        )

        return dependent_agents

    def check_agent_dependencies(self, agent_id: str) -> list[str]:
        """
        Check which workflows depend on a specific agent.

        Args:
            agent_id: Agent identifier

        Returns:
            List of workflow IDs that reference this agent

        Requirements: 3.5, 8.3
        """
        import json

        from src.config.workflow_models import WorkflowsConfig

        # Use config_loader's directory if available
        if hasattr(self.config_loader, "config_dir"):
            workflows_path = Path(self.config_loader.config_dir) / "workflows.json"
        else:
            workflows_path = config_path("workflows.json")

        if not workflows_path.exists():
            return []

        with open(workflows_path) as f:
            workflows_data = json.load(f)

        workflows_config = WorkflowsConfig(**workflows_data)

        # Find workflows that reference this agent
        dependent_workflows = [
            workflow.id
            for workflow in workflows_config.workflows
            if agent_id in workflow.get_all_agent_ids()
        ]

        logger.debug(
            "Checked agent dependencies",
            agent_id=agent_id,
            dependent_count=len(dependent_workflows),
        )

        return dependent_workflows

    def validate_tool_deletion(self, tool_id: str) -> None:
        """
        Validate that a tool can be safely deleted.

        Args:
            tool_id: Tool identifier

        Raises:
            DependencyError: If the tool is referenced by agents

        Requirements: 3.5, 8.2
        """
        dependent_agents = self.check_tool_dependencies(tool_id)

        if dependent_agents:
            logger.warning(
                "Cannot delete tool with dependencies",
                tool_id=tool_id,
                dependent_agents=dependent_agents,
            )
            raise DependencyError(
                f"Cannot delete tool '{tool_id}' because it is referenced by agents: {', '.join(dependent_agents)}",
                dependents=dependent_agents,
            )

        logger.debug("Tool can be safely deleted", tool_id=tool_id)

    def validate_agent_deletion(self, agent_id: str) -> None:
        """
        Validate that an agent can be safely deleted.

        Args:
            agent_id: Agent identifier

        Raises:
            DependencyError: If the agent is referenced by workflows

        Requirements: 3.5, 8.3
        """
        dependent_workflows = self.check_agent_dependencies(agent_id)

        if dependent_workflows:
            logger.warning(
                "Cannot delete agent with dependencies",
                agent_id=agent_id,
                dependent_workflows=dependent_workflows,
            )
            raise DependencyError(
                f"Cannot delete agent '{agent_id}' because it is referenced by workflows: {', '.join(dependent_workflows)}",
                dependents=dependent_workflows,
            )

        logger.debug("Agent can be safely deleted", agent_id=agent_id)


# Singleton instance
_validator: DependencyValidator | None = None


def get_validator() -> DependencyValidator:
    """
    Get the singleton dependency validator instance.

    Returns:
        DependencyValidator instance
    """
    global _validator
    if _validator is None:
        _validator = DependencyValidator()
    return _validator
