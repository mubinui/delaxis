"""Multi-layer configuration manager with hot reload."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from watchdog.events import DirModifiedEvent, FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from src.audit_logging import get_logger
from src.config.agent_models import AgentConfig, AgentsConfig
from src.config.cache_models import CacheConfig
from src.config.execution_models import ExecutionConfig
from src.config.paths import config_dir as default_config_dir
from src.config.topology_models import TopologyConfig
from src.config.workflow_models import WorkflowConfig, WorkflowsConfig

logger = get_logger(__name__)


class ValidationResult(BaseModel):
    """Result of configuration validation."""

    valid: bool
    errors: list[str] = []
    warnings: list[str] = []


class EffectiveConfig(BaseModel):
    """Effective configuration after applying hierarchy."""

    execution: ExecutionConfig
    cache: CacheConfig
    agent: AgentConfig | None = None
    workflow: WorkflowConfig | None = None
    topology: TopologyConfig | None = None


class ConfigurationError(Exception):
    """Raised when configuration operations fail."""

    pass


class ConfigFileHandler(FileSystemEventHandler):
    """Handler for configuration file changes."""

    def __init__(self, manager: "ConfigurationManager"):
        self.manager = manager
        self._debounce_timers: dict[str, asyncio.Task[None]] = {}

    def on_modified(self, event: DirModifiedEvent | FileModifiedEvent) -> None:
        """Handle file modification events."""
        if event.is_directory:
            return

        file_path = Path(os.fsdecode(event.src_path))
        if file_path.suffix != ".json":
            return

        logger.info(f"Configuration file modified: {file_path}")

        # Debounce rapid file changes
        if str(file_path) in self._debounce_timers:
            self._debounce_timers[str(file_path)].cancel()

        # Schedule reload after short delay
        loop = asyncio.get_event_loop()
        task = loop.create_task(self._debounced_reload(file_path))
        self._debounce_timers[str(file_path)] = task

    async def _debounced_reload(self, file_path: Path) -> None:
        """Reload configuration after debounce delay."""
        await asyncio.sleep(0.5)  # 500ms debounce
        try:
            await self.manager.reload_config_file(file_path)
        except Exception as e:
            logger.error(f"Failed to reload config file {file_path}: {e}")


class ConfigurationManager:
    """
    Multi-layer configuration manager with validation and hot reload.

    Configuration hierarchy (highest to lowest priority):
    1. Runtime overrides (passed at execution time)
    2. Agent-specific configuration
    3. Workflow-specific configuration
    4. Global configuration
    """

    def __init__(self, config_dir: Path | str | None = None):
        """
        Initialize configuration manager.

        Args:
            config_dir: Directory containing configuration files
        """
        self.config_dir = Path(config_dir) if config_dir is not None else default_config_dir()
        self._observer: BaseObserver | None = None
        self._watching = False

        # Configuration caches
        self._global_execution: ExecutionConfig | None = None
        self._global_cache: CacheConfig | None = None
        self._agents: AgentsConfig | None = None
        self._workflows: WorkflowsConfig | None = None
        self._topologies: dict[str, TopologyConfig] = {}

        # File paths
        self._execution_file = self.config_dir / "execution.json"
        self._cache_file = self.config_dir / "cache.json"
        self._agents_file = self.config_dir / "agents.json"
        self._workflows_file = self.config_dir / "workflows.json"
        self._topologies_dir = self.config_dir / "topologies"

    def load_execution_config(self, use_cache: bool = True) -> ExecutionConfig:
        """
        Load global execution configuration.

        Args:
            use_cache: Whether to use cached configuration

        Returns:
            ExecutionConfig instance

        Raises:
            ConfigurationError: If loading or validation fails
        """
        if use_cache and self._global_execution is not None:
            return self._global_execution

        try:
            if not self._execution_file.exists():
                logger.warning("Execution config not found, using defaults")
                config = ExecutionConfig()
            else:
                with open(self._execution_file) as f:
                    data = json.load(f)
                config = ExecutionConfig(**data)

            self._global_execution = config
            logger.info("Loaded execution configuration")
            return config

        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            raise ConfigurationError(f"Failed to load execution config: {e}") from e

    def load_cache_config(self, use_cache: bool = True) -> CacheConfig:
        """
        Load global cache configuration.

        Args:
            use_cache: Whether to use cached configuration

        Returns:
            CacheConfig instance

        Raises:
            ConfigurationError: If loading or validation fails
        """
        if use_cache and self._global_cache is not None:
            return self._global_cache

        try:
            if not self._cache_file.exists():
                logger.warning("Cache config not found, using defaults")
                config = CacheConfig()
            else:
                with open(self._cache_file) as f:
                    data = json.load(f)
                config = CacheConfig(**data)

            self._global_cache = config
            logger.info("Loaded cache configuration")
            return config

        except (json.JSONDecodeError, ValidationError) as e:
            raise ConfigurationError(f"Failed to load cache config: {e}") from e

    def load_agents_config(self, use_cache: bool = True) -> AgentsConfig:
        """
        Load agents configuration.

        Args:
            use_cache: Whether to use cached configuration

        Returns:
            AgentsConfig instance

        Raises:
            ConfigurationError: If loading or validation fails
        """
        if use_cache and self._agents is not None:
            return self._agents

        try:
            if not self._agents_file.exists():
                raise ConfigurationError(f"Agents config not found: {self._agents_file}")

            with open(self._agents_file) as f:
                data = json.load(f)

            config = AgentsConfig(**data)
            try:
                config.validate_all()
            except ValueError as e:
                raise ConfigurationError(f"Agent validation failed: {e}") from e

            self._agents = config
            logger.info(f"Loaded {len(config.agents)} agents")
            return config

        except (json.JSONDecodeError, ValidationError) as e:
            raise ConfigurationError(f"Failed to load agents config: {e}") from e

    def load_workflows_config(self, use_cache: bool = True) -> WorkflowsConfig:
        """
        Load workflows configuration.

        Args:
            use_cache: Whether to use cached configuration

        Returns:
            WorkflowsConfig instance

        Raises:
            ConfigurationError: If loading or validation fails
        """
        if use_cache and self._workflows is not None:
            return self._workflows

        try:
            if not self._workflows_file.exists():
                raise ConfigurationError(f"Workflows config not found: {self._workflows_file}")

            with open(self._workflows_file) as f:
                data = json.load(f)

            config = WorkflowsConfig(**data)
            config.validate_all()

            self._workflows = config
            logger.info(f"Loaded {len(config.workflows)} workflows")
            return config

        except (json.JSONDecodeError, ValidationError) as e:
            raise ConfigurationError(f"Failed to load workflows config: {e}") from e

    def load_topology_config(self, topology_id: str, use_cache: bool = True) -> TopologyConfig:
        """
        Load a specific topology configuration.

        Args:
            topology_id: ID of the topology to load
            use_cache: Whether to use cached configuration

        Returns:
            TopologyConfig instance

        Raises:
            ConfigurationError: If loading or validation fails
        """
        if use_cache and topology_id in self._topologies:
            return self._topologies[topology_id]

        try:
            topology_file = self._topologies_dir / f"{topology_id}.json"
            if not topology_file.exists():
                raise ConfigurationError(f"Topology config not found: {topology_file}")

            with open(topology_file) as f:
                data = json.load(f)

            config = TopologyConfig(**data)
            errors = config.validate_topology()
            if errors:
                raise ConfigurationError(f"Topology validation failed: {errors}")

            self._topologies[topology_id] = config
            logger.info(f"Loaded topology '{topology_id}' with {len(config.nodes)} nodes")
            return config

        except (json.JSONDecodeError, ValidationError) as e:
            raise ConfigurationError(f"Failed to load topology config: {e}") from e

    def get_effective_config(
        self,
        workflow_id: str | None = None,
        agent_id: str | None = None,
        runtime_overrides: dict[str, Any] | None = None,
    ) -> EffectiveConfig:
        """
        Get effective configuration by applying hierarchy.

        Args:
            workflow_id: Optional workflow ID
            agent_id: Optional agent ID
            runtime_overrides: Optional runtime configuration overrides

        Returns:
            EffectiveConfig with merged configuration

        Raises:
            ConfigurationError: If configuration cannot be loaded
        """
        # Load base configurations
        execution = self.load_execution_config()
        cache = self.load_cache_config()

        # Load workflow and agent if specified
        workflow = None
        agent = None
        topology = None

        if workflow_id:
            workflows = self.load_workflows_config()
            workflow = workflows.get_workflow(workflow_id)
            if workflow is None:
                raise ConfigurationError(f"Workflow not found: {workflow_id}")

        if agent_id:
            agents = self.load_agents_config()
            agent = agents.get_agent(agent_id)
            if agent is None:
                raise ConfigurationError(f"Agent not found: {agent_id}")

        # Apply runtime overrides if provided
        if runtime_overrides:
            # TODO: Implement runtime override merging
            pass

        return EffectiveConfig(
            execution=execution, cache=cache, agent=agent, workflow=workflow, topology=topology
        )

    def validate_config(self, config_type: str, data: dict[str, Any]) -> ValidationResult:
        """
        Validate configuration data without loading.

        Args:
            config_type: Type of configuration ('execution', 'cache', 'agents', 'workflows', 'topology')
            data: Configuration data to validate

        Returns:
            ValidationResult with validation status and errors
        """
        result = ValidationResult(valid=True)

        try:
            if config_type == "execution":
                ExecutionConfig(**data)
            elif config_type == "cache":
                CacheConfig(**data)
            elif config_type == "agents":
                AgentsConfig(**data).validate_all()
            elif config_type == "workflows":
                WorkflowsConfig(**data).validate_all()
            elif config_type == "topology":
                errors = TopologyConfig(**data).validate_topology()
                if errors:
                    result.valid = False
                    result.errors = errors
            else:
                result.valid = False
                result.errors.append(f"Unknown config type: {config_type}")

        except ValidationError as e:
            result.valid = False
            result.errors = [str(err) for err in e.errors()]
        except Exception as e:
            result.valid = False
            result.errors.append(str(e))

        return result

    def check_referential_integrity(self) -> ValidationResult:
        """
        Check referential integrity across all configurations.

        Returns:
            ValidationResult with integrity check results
        """
        result = ValidationResult(valid=True)

        try:
            agents = self.load_agents_config()
            workflows = self.load_workflows_config()

            agent_ids = {agent.id for agent in agents.agents}

            # Check workflow agent references
            for workflow in workflows.workflows:
                workflow_agent_ids = workflow.get_all_agent_ids()
                missing_agents = workflow_agent_ids - agent_ids
                if missing_agents:
                    result.valid = False
                    result.errors.append(
                        f"Workflow '{workflow.id}' references non-existent agents: {missing_agents}"
                    )

        except ConfigurationError as e:
            result.valid = False
            result.errors.append(str(e))

        return result

    async def reload_config_file(self, file_path: Path) -> None:
        """
        Reload a specific configuration file.

        Args:
            file_path: Path to the configuration file

        Raises:
            ConfigurationError: If reload fails
        """
        logger.info(f"Reloading configuration file: {file_path}")

        try:
            # Determine config type and reload
            if file_path == self._execution_file:
                self._global_execution = None
                self.load_execution_config(use_cache=False)
            elif file_path == self._cache_file:
                self._global_cache = None
                self.load_cache_config(use_cache=False)
            elif file_path == self._agents_file:
                # Validate before clearing cache
                with open(file_path) as f:
                    data = json.load(f)
                validation = self.validate_config("agents", data)
                if not validation.valid:
                    logger.error(
                        f"Invalid agents config, keeping previous version: {validation.errors}"
                    )
                    raise ConfigurationError(f"Validation failed: {validation.errors}")
                self._agents = None
                self.load_agents_config(use_cache=False)
            elif file_path == self._workflows_file:
                # Validate before clearing cache
                with open(file_path) as f:
                    data = json.load(f)
                validation = self.validate_config("workflows", data)
                if not validation.valid:
                    logger.error(
                        f"Invalid workflows config, keeping previous version: {validation.errors}"
                    )
                    raise ConfigurationError(f"Validation failed: {validation.errors}")
                self._workflows = None
                self.load_workflows_config(use_cache=False)
            elif file_path.parent == self._topologies_dir:
                topology_id = file_path.stem
                # Validate before clearing cache
                with open(file_path) as f:
                    data = json.load(f)
                validation = self.validate_config("topology", data)
                if not validation.valid:
                    logger.error(
                        f"Invalid topology config, keeping previous version: {validation.errors}"
                    )
                    raise ConfigurationError(f"Validation failed: {validation.errors}")
                if topology_id in self._topologies:
                    del self._topologies[topology_id]
                self.load_topology_config(topology_id, use_cache=False)

            logger.info(f"Successfully reloaded configuration: {file_path}")

        except Exception as e:
            logger.error(f"Failed to reload configuration {file_path}: {e}")
            raise ConfigurationError(f"Reload failed: {e}") from e

    def start_watching(self) -> None:
        """Start watching configuration files for changes."""
        if self._watching:
            logger.warning("Already watching configuration files")
            return

        self._observer = Observer()
        handler = ConfigFileHandler(self)

        # Watch config directory
        self._observer.schedule(handler, str(self.config_dir), recursive=True)
        self._observer.start()
        self._watching = True

        logger.info(f"Started watching configuration directory: {self.config_dir}")

    def stop_watching(self) -> None:
        """Stop watching configuration files."""
        if not self._watching or self._observer is None:
            return

        self._observer.stop()
        self._observer.join()
        self._watching = False

        logger.info("Stopped watching configuration files")

    def reload_all(self) -> None:
        """Reload all configurations, bypassing cache."""
        logger.info("Reloading all configurations")

        self._global_execution = None
        self._global_cache = None
        self._agents = None
        self._workflows = None
        self._topologies.clear()

        self.load_execution_config(use_cache=False)
        self.load_cache_config(use_cache=False)
        self.load_agents_config(use_cache=False)
        self.load_workflows_config(use_cache=False)

        logger.info("Successfully reloaded all configurations")


# Singleton instance
_manager: ConfigurationManager | None = None


def get_config_manager(config_dir: Path | str | None = None) -> ConfigurationManager:
    """
    Get the singleton configuration manager instance.

    Args:
        config_dir: Directory containing configuration files

    Returns:
        ConfigurationManager instance
    """
    global _manager
    if _manager is None:
        _manager = ConfigurationManager(config_dir)
    return _manager
