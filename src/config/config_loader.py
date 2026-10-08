"""Centralized configuration loader for JSON config files with hot-reload support."""

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from watchdog.events import DirModifiedEvent, FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from src.config.paths import config_dir as default_config_dir

logger = logging.getLogger(__name__)


class ConfigFileHandler(FileSystemEventHandler):
    """File system event handler for configuration file changes."""

    def __init__(self, loader: "ConfigLoader"):
        """Initialize handler with reference to config loader."""
        self.loader = loader

    def on_modified(self, event: DirModifiedEvent | FileModifiedEvent) -> None:
        """Handle file modification events."""
        if event.is_directory:
            return

        file_path = Path(os.fsdecode(event.src_path))
        if (
            file_path.suffix == ".json"
            and file_path.parent.resolve() == self.loader.config_dir.resolve()
        ):
            logger.info(f"Configuration file modified: {file_path.name}")
            self.loader._reload_single_file(file_path)


class ConfigLoader:
    """
    Centralized configuration loader for JSON files.

    Loads and caches configuration files with optional hot-reload capability.
    Provides validation and error handling for configuration access.
    """

    def __init__(self, config_dir: Path | None = None, enable_hot_reload: bool = False):
        """
        Initialize configuration loader.

        Args:
            config_dir: Directory containing configuration files
            enable_hot_reload: Enable automatic reload on file changes
        """
        self.config_dir = config_dir if config_dir is not None else default_config_dir()
        self.enable_hot_reload = enable_hot_reload
        self._cache: dict[str, dict[str, Any]] = {}
        self._last_loaded: dict[str, datetime] = {}
        self._observer: BaseObserver | None = None

        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Load all configurations
        self._load_all()

        # Start file watcher if hot reload is enabled
        if self.enable_hot_reload:
            self._start_file_watcher()

    def _load_all(self) -> None:
        """Load all JSON configuration files from the config directory."""
        logger.info(f"Loading configurations from {self.config_dir}")

        for config_file in self.config_dir.glob("*.json"):
            self._load_file(config_file)

    def _load_file(self, file_path: Path) -> None:
        """
        Load a single configuration file.

        Args:
            file_path: Path to configuration file
        """
        try:
            with open(file_path, encoding="utf-8") as f:
                config_data = json.load(f)

            config_name = file_path.stem
            self._cache[config_name] = config_data
            self._last_loaded[config_name] = datetime.now(UTC)

            logger.info(
                f"Loaded configuration: {config_name} "
                f"(version: {config_data.get('version', 'unknown')})"
            )
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON in {file_path}: {e}", exc_info=True)
            raise ValueError(f"Invalid JSON in {file_path}: {e}") from e
        except Exception as e:
            logger.error(f"Failed to load configuration from {file_path}: {e}", exc_info=True)
            raise

    def _reload_single_file(self, file_path: Path) -> None:
        """
        Reload a single configuration file.

        Args:
            file_path: Path to configuration file
        """
        try:
            self._load_file(file_path)
            logger.info(f"Reloaded configuration: {file_path.stem}")
        except Exception as e:
            logger.error(f"Failed to reload {file_path}: {e}")

    def _start_file_watcher(self) -> None:
        """Start watching configuration directory for changes."""
        try:
            event_handler = ConfigFileHandler(self)
            self._observer = Observer()
            self._observer.schedule(event_handler, str(self.config_dir), recursive=False)
            self._observer.start()
            logger.info(f"Started configuration file watcher for {self.config_dir}")
        except Exception as e:
            logger.error(f"Failed to start file watcher: {e}")
            self.enable_hot_reload = False

    def stop_file_watcher(self) -> None:
        """Stop the file watcher."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            logger.info("Stopped configuration file watcher")

    def get_config(self, config_name: str) -> dict[str, Any]:
        """
        Get configuration by name.

        Args:
            config_name: Name of configuration file (without .json extension)

        Returns:
            Configuration dictionary

        Raises:
            FileNotFoundError: If configuration file doesn't exist
        """
        if config_name not in self._cache:
            # Try to load the file if it exists but wasn't loaded yet
            config_file = self.config_dir / f"{config_name}.json"
            if config_file.exists():
                self._load_file(config_file)
            else:
                raise FileNotFoundError(
                    f"Configuration '{config_name}' not found in {self.config_dir}"
                )

        return self._cache[config_name]

    def set_config(self, config_name: str, config: dict[str, Any]) -> None:
        """Replace one cached config with what was just written to disk.

        Writers hand the loader the exact structure they saved, so readers see
        the new state immediately, with or without the file watcher.
        """
        self._cache[config_name] = config
        self._last_loaded[config_name] = datetime.now(UTC)

    def _items(self, config_name: str, key: str) -> list[dict[str, Any]]:
        items = self.get_config(config_name).get(key, [])
        return list(items) if isinstance(items, list) else []

    def get_agents(self) -> list[dict[str, Any]]:
        """Get all agent configurations."""
        return self._items("agents", "agents")

    def get_agent_by_id(self, agent_id: str) -> dict[str, Any] | None:
        """Get agent configuration by ID."""
        agents = self.get_agents()
        return next((agent for agent in agents if agent["id"] == agent_id), None)

    def get_tools(self) -> list[dict[str, Any]]:
        """Get all tools configurations."""
        return self._items("tools", "tools")

    def get_tool_by_id(self, tool_id: str) -> dict[str, Any] | None:
        """Get tool configuration by ID."""
        tools = self.get_tools()
        return next((tool for tool in tools if tool["id"] == tool_id), None)

    def get_workflows(self) -> list[dict[str, Any]]:
        """Get all workflows configurations."""
        return self._items("workflows", "workflows")

    def get_workflow_by_id(self, workflow_id: str) -> dict[str, Any] | None:
        """Get workflow configuration by ID."""
        workflows = self.get_workflows()
        return next((wf for wf in workflows if wf["id"] == workflow_id), None)

    def get_api_providers(self) -> list[dict[str, Any]]:
        """Get all api providers configurations."""
        return self._items("api_providers", "providers")

    def get_api_provider_by_id(self, provider_id: str) -> dict[str, Any] | None:
        """Get API provider configuration by ID."""
        providers = self.get_api_providers()
        return next((p for p in providers if p["id"] == provider_id), None)

    def get_prompts(self) -> list[dict[str, Any]]:
        """Get all prompts configurations."""
        return self._items("prompt_templates", "contexts")

    def get_prompt_by_id(self, prompt_id: str) -> dict[str, Any] | None:
        """Get prompt template by ID."""
        prompts = self.get_prompts()
        return next((p for p in prompts if p["id"] == prompt_id), None)

    def reload_all(self) -> None:
        """Manually reload all configuration files."""
        logger.info("Manually reloading all configurations")
        self._cache.clear()
        self._last_loaded.clear()
        self._load_all()

    def get_last_loaded(self, config_name: str) -> datetime | None:
        """Get timestamp of last load for a configuration."""
        return self._last_loaded.get(config_name)

    def is_loaded(self, config_name: str) -> bool:
        """Check if a configuration is loaded."""
        return config_name in self._cache

    def get_config_version(self, config_name: str) -> str:
        """Get version string from configuration."""
        config = self.get_config(config_name)
        return str(config.get("version", "unknown"))

    def __enter__(self) -> "ConfigLoader":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Context manager exit - stop file watcher."""
        self.stop_file_watcher()


# Global configuration loader instance
_config_loader: ConfigLoader | None = None


def get_config_loader(
    config_dir: Path | None = None, enable_hot_reload: bool = False, reload: bool = False
) -> ConfigLoader:
    """
    Get or initialize the global configuration loader.

    Args:
        config_dir: Directory containing configuration files
        enable_hot_reload: Enable automatic reload on file changes
        reload: Force reload of all configurations

    Returns:
        ConfigLoader instance
    """
    global _config_loader

    if _config_loader is None or reload:
        if _config_loader is not None:
            _config_loader.stop_file_watcher()
        _config_loader = ConfigLoader(config_dir, enable_hot_reload)

    return _config_loader


def reset_config_loader() -> None:
    """Reset the global configuration loader (useful for testing)."""
    global _config_loader
    if _config_loader is not None:
        _config_loader.stop_file_watcher()
        _config_loader = None
