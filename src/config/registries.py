"""Runtime registries for managing dynamic API providers and prompts."""

import os
from typing import Any

import httpx

from src.audit_logging import get_logger
from src.config.dynamic_models import (
    AuthScheme,
    PromptTemplate,
    ProviderConfig,
    ProviderType,
)
from src.config.loader import ConfigurationError, get_loader

logger = get_logger(__name__)


class ProviderRegistry:
    """Registry for managing API providers and their instances."""

    def __init__(self) -> None:
        """Initialize the provider registry."""
        self._providers: dict[str, ProviderConfig] = {}
        self._instances: dict[str, Any] = {}

    def register(self, provider: ProviderConfig) -> None:
        """
        Register a provider configuration.

        Args:
            provider: Provider configuration to register
        """
        self._providers[provider.id] = provider
        logger.info(
            "Registered provider",
            provider_id=provider.id,
            provider_type=provider.type.value,
            enabled=provider.enabled,
        )

    def unregister(self, provider_id: str) -> None:
        """
        Unregister a provider.

        Args:
            provider_id: ID of provider to unregister
        """
        if provider_id in self._providers:
            del self._providers[provider_id]
            logger.info("Unregistered provider", provider_id=provider_id)

        if provider_id in self._instances:
            del self._instances[provider_id]

    def get_provider(self, provider_id: str) -> ProviderConfig | None:
        """
        Get provider configuration by ID.

        Args:
            provider_id: Provider ID

        Returns:
            Provider configuration or None if not found
        """
        return self._providers.get(provider_id)

    def get_instance(self, provider_id: str) -> Any:
        """
        Get or create provider instance.

        Args:
            provider_id: Provider ID

        Returns:
            Provider instance

        Raises:
            ValueError: If provider not found or disabled
        """
        # Return cached instance if available
        if provider_id in self._instances:
            return self._instances[provider_id]

        # Get provider config
        provider = self.get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Provider not found: {provider_id}")

        if not provider.enabled:
            raise ValueError(f"Provider disabled: {provider_id}")

        # Create instance based on provider type
        instance = self._create_instance(provider)
        self._instances[provider_id] = instance

        logger.info("Created provider instance", provider_id=provider_id)
        return instance

    def _create_instance(self, provider: ProviderConfig) -> Any:
        """
        Create a provider instance.

        Args:
            provider: Provider configuration

        Returns:
            Provider instance
        """
        if provider.type == ProviderType.LLM:
            return self._create_llm_instance(provider)
        elif provider.type == ProviderType.TOOL:
            return self._create_tool_instance(provider)
        else:
            # Generic instance - just return config
            return provider

    def _create_llm_instance(self, provider: ProviderConfig) -> httpx.AsyncClient:
        """
        Create an HTTP client for LLM provider.

        Args:
            provider: Provider configuration

        Returns:
            Configured HTTP client
        """
        headers = {}

        # Add authentication
        if provider.auth:
            if provider.auth.scheme == AuthScheme.BEARER:
                if provider.auth.env_var:
                    api_key = os.getenv(provider.auth.env_var)
                    if not api_key:
                        raise ValueError(f"Environment variable not set: {provider.auth.env_var}")
                    headers["Authorization"] = f"Bearer {api_key}"
            elif provider.auth.scheme == AuthScheme.API_KEY:
                if provider.auth.env_var and provider.auth.header_name:
                    api_key = os.getenv(provider.auth.env_var)
                    if api_key:
                        headers[provider.auth.header_name] = api_key

        # Add default headers
        if provider.request_defaults and provider.request_defaults.headers:
            headers.update(provider.request_defaults.headers)

        # Create client
        timeout = provider.request_defaults.timeout_seconds if provider.request_defaults else 120

        return httpx.AsyncClient(
            base_url=provider.base_url or "",
            headers=headers,
            timeout=timeout,
        )

    def _create_tool_instance(self, provider: ProviderConfig) -> Any:
        """
        Create a tool instance by importing from entrypoint.

        Args:
            provider: Provider configuration

        Returns:
            Tool instance
        """
        if not provider.entrypoint:
            return provider

        try:
            # Parse entrypoint like "src.agents.connectors.duckduckgo:DuckDuckGoConnector"
            module_path, class_name = provider.entrypoint.split(":")
            module = __import__(module_path, fromlist=[class_name])
            cls = getattr(module, class_name)

            # Instantiate with settings
            return cls(**provider.settings)

        except Exception as e:
            logger.error(
                "Failed to create tool instance",
                provider_id=provider.id,
                error=str(e),
            )
            raise ValueError(f"Failed to create tool instance for {provider.id}: {e}") from e

    def list_providers(self) -> list[str]:
        """List all registered provider IDs."""
        return list(self._providers.keys())

    def list_enabled_providers(self) -> list[str]:
        """List all enabled provider IDs."""
        return [pid for pid, p in self._providers.items() if p.enabled]

    def reload_from_config(self) -> None:
        """Reload providers from configuration file."""
        logger.info("Reloading providers from configuration")

        try:
            loader = get_loader()
            config = loader.load_providers(use_cache=False)

            # Clear existing instances but keep configs for comparison
            old_providers = set(self._providers.keys())
            self._instances.clear()

            # Register new providers
            self._providers.clear()
            for provider in config.providers:
                self.register(provider)

            new_providers = set(self._providers.keys())

            # Log changes
            added = new_providers - old_providers
            removed = old_providers - new_providers

            if added:
                logger.info("Added providers", provider_ids=list(added))
            if removed:
                logger.info("Removed providers", provider_ids=list(removed))

            logger.info("Successfully reloaded providers")

        except ConfigurationError as e:
            logger.error("Failed to reload providers", error=str(e))
            raise


class PromptRegistry:
    """Registry for managing prompt templates."""

    def __init__(self) -> None:
        """Initialize the prompt registry."""
        self._prompts: dict[str, PromptTemplate] = {}
        self._fallbacks: dict[str, str] = {}

    def register(self, prompt: PromptTemplate) -> None:
        """
        Register a prompt template.

        Args:
            prompt: Prompt template to register
        """
        self._prompts[prompt.id] = prompt
        logger.info(
            "Registered prompt template",
            prompt_id=prompt.id,
            target=prompt.target,
        )

    def unregister(self, prompt_id: str) -> None:
        """
        Unregister a prompt template.

        Args:
            prompt_id: ID of prompt to unregister
        """
        if prompt_id in self._prompts:
            del self._prompts[prompt_id]
            logger.info("Unregistered prompt template", prompt_id=prompt_id)

    def get_prompt(self, prompt_id: str) -> PromptTemplate | None:
        """
        Get prompt template by ID.

        Args:
            prompt_id: Prompt ID

        Returns:
            Prompt template or None if not found
        """
        return self._prompts.get(prompt_id)

    def get_prompt_text(self, prompt_id: str, **kwargs: Any) -> str:
        """
        Get prompt text, optionally with variable substitution.

        Args:
            prompt_id: Prompt ID
            **kwargs: Variables to substitute in the template

        Returns:
            Prompt text (potentially with substitutions)

        Raises:
            ValueError: If prompt not found
        """
        prompt = self.get_prompt(prompt_id)
        if prompt is None:
            fallback = self._fallbacks.get("missing_prompt", "Prompt not found")
            logger.warning("Prompt not found", prompt_id=prompt_id)
            return fallback

        text = prompt.prompt

        # Simple variable substitution
        if kwargs:
            for key, value in kwargs.items():
                text = text.replace(f"{{{key}}}", str(value))

        return text

    def get_prompts_by_target(self, target: str) -> list[PromptTemplate]:
        """
        Get all prompts for a specific target.

        Args:
            target: Target agent type

        Returns:
            List of prompt templates
        """
        return [p for p in self._prompts.values() if p.target == target]

    def list_prompts(self) -> list[str]:
        """List all registered prompt IDs."""
        return list(self._prompts.keys())

    def set_fallbacks(self, fallbacks: dict[str, str]) -> None:
        """Set fallback messages."""
        self._fallbacks = fallbacks

    def reload_from_config(self) -> None:
        """Reload prompts from configuration file."""
        logger.info("Reloading prompts from configuration")

        try:
            loader = get_loader()
            config = loader.load_prompts(use_cache=False)

            # Clear and reload
            old_prompts = set(self._prompts.keys())
            self._prompts.clear()

            for prompt in config.contexts:
                self.register(prompt)

            self.set_fallbacks(config.fallbacks)

            new_prompts = set(self._prompts.keys())

            # Log changes
            added = new_prompts - old_prompts
            removed = old_prompts - new_prompts

            if added:
                logger.info("Added prompts", prompt_ids=list(added))
            if removed:
                logger.info("Removed prompts", prompt_ids=list(removed))

            logger.info("Successfully reloaded prompts")

        except ConfigurationError as e:
            logger.error("Failed to reload prompts", error=str(e))
            raise


# Singleton instances
_provider_registry: ProviderRegistry | None = None
_prompt_registry: PromptRegistry | None = None


def get_provider_registry() -> ProviderRegistry:
    """Get the singleton provider registry instance."""
    global _provider_registry
    if _provider_registry is None:
        _provider_registry = ProviderRegistry()
        # Load initial configuration
        try:
            loader = get_loader()
            config = loader.load_providers()
            for provider in config.providers:
                _provider_registry.register(provider)
        except Exception as e:
            logger.error("Failed to initialize provider registry", error=str(e))
    return _provider_registry


def get_prompt_registry() -> PromptRegistry:
    """Get the singleton prompt registry instance."""
    global _prompt_registry
    if _prompt_registry is None:
        _prompt_registry = PromptRegistry()
        # Load initial configuration
        try:
            loader = get_loader()
            config = loader.load_prompts()
            for prompt in config.contexts:
                _prompt_registry.register(prompt)
            _prompt_registry.set_fallbacks(config.fallbacks)
        except Exception as e:
            logger.error("Failed to initialize prompt registry", error=str(e))
    return _prompt_registry
