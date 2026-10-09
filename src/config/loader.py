"""Configuration loader service for dynamic JSON configs."""

import json
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv
from pydantic import ValidationError

from src.audit_logging import get_logger
from src.config.agent_models import AgentsConfig
from src.config.dynamic_models import APIProvidersConfig, PromptTemplatesConfig
from src.config.paths import config_dir as default_config_dir
from src.config.tool_models import ToolsConfig

logger = get_logger(__name__)

# Load environment variables from the .env in the working directory: the one the
# settings read. A bare load_dotenv() searches up from this file instead, so a
# server started elsewhere (a test run, a container) picked up the repository's.
load_dotenv(find_dotenv(usecwd=True))


class ConfigurationError(Exception):
    """Raised when configuration loading or validation fails."""

    pass


class ConfigurationLoader:
    """Service for loading and validating dynamic JSON configurations."""

    def __init__(self, config_dir: Path | str | None = None) -> None:
        """
        Initialize the configuration loader.

        Args:
            config_dir: Directory containing configuration JSON files
        """
        self.config_dir = Path(config_dir) if config_dir is not None else default_config_dir()
        self._providers_cache: APIProvidersConfig | None = None
        self._prompts_cache: PromptTemplatesConfig | None = None
        self._tools_cache: ToolsConfig | None = None
        self._agents_cache: AgentsConfig | None = None
        self._providers_file = self.config_dir / "api_providers.json"
        self._prompts_file = self.config_dir / "prompt_templates.json"
        self._tools_file = self.config_dir / "tools.json"
        self._agents_file = self.config_dir / "agents.json"

    def load_providers(self, use_cache: bool = True) -> APIProvidersConfig:
        """
        Load and validate API providers configuration.

        Args:
            use_cache: If True, return cached config if available

        Returns:
            Validated API providers configuration

        Raises:
            ConfigurationError: If loading or validation fails
        """
        if use_cache and self._providers_cache is not None:
            logger.debug("Returning cached API providers configuration")
            return self._providers_cache

        try:
            logger.info(
                "Loading API providers configuration",
                file=str(self._providers_file),
            )

            if not self._providers_file.exists():
                raise ConfigurationError(f"API providers config not found: {self._providers_file}")

            with open(self._providers_file) as f:
                data = json.load(f)

            config = APIProvidersConfig(**data)
            self._providers_cache = config

            logger.info(
                "Successfully loaded API providers",
                provider_count=len(config.providers),
                enabled_count=len(config.get_enabled_providers()),
            )

            return config

        except json.JSONDecodeError as e:
            raise ConfigurationError(f"Invalid JSON in {self._providers_file}: {e}") from e
        except ValidationError as e:
            raise ConfigurationError(f"Validation failed for {self._providers_file}: {e}") from e
        except Exception as e:
            raise ConfigurationError(f"Failed to load providers config: {e}") from e

    def load_prompts(self, use_cache: bool = True) -> PromptTemplatesConfig:
        """
        Load and validate prompt templates configuration.

        Args:
            use_cache: If True, return cached config if available

        Returns:
            Validated prompt templates configuration

        Raises:
            ConfigurationError: If loading or validation fails
        """
        if use_cache and self._prompts_cache is not None:
            logger.debug("Returning cached prompt templates configuration")
            return self._prompts_cache

        try:
            logger.info(
                "Loading prompt templates configuration",
                file=str(self._prompts_file),
            )

            if not self._prompts_file.exists():
                raise ConfigurationError(f"Prompt templates config not found: {self._prompts_file}")

            with open(self._prompts_file) as f:
                data = json.load(f)

            config = PromptTemplatesConfig(**data)
            self._prompts_cache = config

            logger.info(
                "Successfully loaded prompt templates",
                template_count=len(config.contexts),
            )

            return config

        except json.JSONDecodeError as e:
            raise ConfigurationError(f"Invalid JSON in {self._prompts_file}: {e}") from e
        except ValidationError as e:
            raise ConfigurationError(f"Validation failed for {self._prompts_file}: {e}") from e
        except Exception as e:
            raise ConfigurationError(f"Failed to load prompts config: {e}") from e

    def load_tools(self, use_cache: bool = True) -> ToolsConfig:
        """
        Load and validate tools configuration.

        Args:
            use_cache: If True, return cached config if available

        Returns:
            Validated tools configuration

        Raises:
            ConfigurationError: If loading or validation fails
        """
        if use_cache and self._tools_cache is not None:
            logger.debug("Returning cached tools configuration")
            return self._tools_cache

        try:
            logger.info(
                "Loading tools configuration",
                file=str(self._tools_file),
            )

            if not self._tools_file.exists():
                raise ConfigurationError(f"Tools config not found: {self._tools_file}")

            with open(self._tools_file) as f:
                data = json.load(f)

            config = ToolsConfig(**data)
            config.validate_all()
            self._tools_cache = config

            logger.info(
                "Successfully loaded tools",
                tool_count=len(config.tools),
                enabled_count=len(config.get_enabled_tools()),
            )

            return config

        except json.JSONDecodeError as e:
            raise ConfigurationError(f"Invalid JSON in {self._tools_file}: {e}") from e
        except ValidationError as e:
            raise ConfigurationError(f"Validation failed for {self._tools_file}: {e}") from e
        except Exception as e:
            raise ConfigurationError(f"Failed to load tools config: {e}") from e

    def load_agents(self, use_cache: bool = True) -> AgentsConfig:
        """
        Load and validate agents configuration.

        Args:
            use_cache: If True, return cached config if available

        Returns:
            Validated agents configuration

        Raises:
            ConfigurationError: If loading or validation fails
        """
        if use_cache and self._agents_cache is not None:
            logger.debug("Returning cached agents configuration")
            return self._agents_cache

        try:
            logger.info(
                "Loading agents configuration",
                file=str(self._agents_file),
            )

            if not self._agents_file.exists():
                raise ConfigurationError(f"Agents config not found: {self._agents_file}")

            with open(self._agents_file) as f:
                data = json.load(f)

            config = AgentsConfig(**data)
            self._agents_cache = config

            logger.info(
                "Successfully loaded agents",
                agent_count=len(config.agents),
            )

            return config

        except json.JSONDecodeError as e:
            raise ConfigurationError(f"Invalid JSON in {self._agents_file}: {e}") from e
        except ValidationError as e:
            raise ConfigurationError(f"Validation failed for {self._agents_file}: {e}") from e
        except Exception as e:
            raise ConfigurationError(f"Failed to load agents config: {e}") from e

    def reload_all(self) -> tuple[APIProvidersConfig, PromptTemplatesConfig, ToolsConfig]:
        """
        Reload all configurations, bypassing cache.

        Returns:
            Tuple of (providers_config, prompts_config, tools_config)

        Raises:
            ConfigurationError: If any config fails to load
        """
        logger.info("Reloading all configurations")

        # Clear caches
        self._providers_cache = None
        self._prompts_cache = None
        self._tools_cache = None

        # Load fresh configs
        providers = self.load_providers(use_cache=False)
        prompts = self.load_prompts(use_cache=False)
        tools = self.load_tools(use_cache=False)

        logger.info("Successfully reloaded all configurations")
        return providers, prompts, tools

    def validate_files(self) -> dict[str, Any]:
        """
        Validate configuration files without caching.

        Returns:
            Dictionary with validation results

        Raises:
            ConfigurationError: If validation fails
        """
        results: dict[str, dict[str, Any]] = {
            "providers": {"valid": False, "errors": []},
            "prompts": {"valid": False, "errors": []},
            "tools": {"valid": False, "errors": []},
        }

        # Validate providers
        try:
            self.load_providers(use_cache=False)
            results["providers"]["valid"] = True
        except ConfigurationError as e:
            results["providers"]["errors"].append(str(e))

        # Validate prompts
        try:
            self.load_prompts(use_cache=False)
            results["prompts"]["valid"] = True
        except ConfigurationError as e:
            results["prompts"]["errors"].append(str(e))

        # Validate tools
        try:
            self.load_tools(use_cache=False)
            results["tools"]["valid"] = True
        except ConfigurationError as e:
            results["tools"]["errors"].append(str(e))

        return results

    def get_config_paths(self) -> dict[str, str]:
        """Get paths to all configuration files."""
        return {
            "providers": str(self._providers_file),
            "prompts": str(self._prompts_file),
            "tools": str(self._tools_file),
            "agents": str(self._agents_file),
        }


# Singleton instance
_loader: ConfigurationLoader | None = None


def get_loader(config_dir: Path | str | None = None) -> ConfigurationLoader:
    """
    Get the singleton configuration loader instance.

    Args:
        config_dir: Directory containing configuration files

    Returns:
        ConfigurationLoader instance
    """
    global _loader
    if _loader is None:
        _loader = ConfigurationLoader(config_dir)
    return _loader


def load_agents_config(config_dir: Path | str | None = None) -> AgentsConfig:
    """
    Convenience function to load agents configuration.

    Args:
        config_dir: Directory containing configuration files

    Returns:
        Validated agents configuration
    """
    loader = get_loader(config_dir)
    return loader.load_agents()
