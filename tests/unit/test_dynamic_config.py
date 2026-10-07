"""Tests for dynamic configuration system."""

import json
from pathlib import Path

import pytest

from src.config.dynamic_models import (
    APIProvidersConfig,
    AuthScheme,
    PromptTemplatesConfig,
    ProviderType,
)
from src.config.loader import ConfigurationError, ConfigurationLoader
from src.config.registries import PromptRegistry, ProviderRegistry


class TestConfigurationLoader:
    """Tests for ConfigurationLoader."""

    def test_load_providers_success(self, tmp_path: Path) -> None:
        """Test successfully loading provider configuration."""
        # Create test config
        config_dir = tmp_path / "configs"
        config_dir.mkdir()

        providers_data = {
            "version": "1.0",
            "last_updated": "2025-11-04T00:00:00Z",
            "providers": [
                {
                    "id": "test_provider",
                    "name": "Test Provider",
                    "type": "llm",
                    "description": "Test",
                    "base_url": "https://api.test.com",
                    "auth": {"scheme": "bearer", "env_var": "TEST_KEY"},
                }
            ],
        }

        (config_dir / "api_providers.json").write_text(json.dumps(providers_data))
        (config_dir / "prompt_templates.json").write_text(
            json.dumps({"version": "1.0", "contexts": [], "fallbacks": {}})
        )

        # Load config
        loader = ConfigurationLoader(config_dir)
        config = loader.load_providers()

        assert isinstance(config, APIProvidersConfig)
        assert len(config.providers) == 1
        assert config.providers[0].id == "test_provider"

    def test_load_providers_missing_file(self, tmp_path: Path) -> None:
        """Test loading providers when file doesn't exist."""
        loader = ConfigurationLoader(tmp_path)

        with pytest.raises(ConfigurationError, match="not found"):
            loader.load_providers()

    def test_load_providers_invalid_json(self, tmp_path: Path) -> None:
        """Test loading providers with invalid JSON."""
        config_dir = tmp_path / "configs"
        config_dir.mkdir()

        (config_dir / "api_providers.json").write_text("invalid json{")

        loader = ConfigurationLoader(config_dir)

        with pytest.raises(ConfigurationError, match="Invalid JSON"):
            loader.load_providers()

    def test_load_prompts_success(self, tmp_path: Path) -> None:
        """Test successfully loading prompt templates."""
        config_dir = tmp_path / "configs"
        config_dir.mkdir()

        prompts_data = {
            "version": "1.0",
            "contexts": [
                {
                    "id": "test_prompt",
                    "target": "response_agent",
                    "description": "Test prompt",
                    "prompt": "You are a test assistant.",
                }
            ],
            "fallbacks": {"missing_prompt": "Prompt not found"},
        }

        (config_dir / "prompt_templates.json").write_text(json.dumps(prompts_data))
        (config_dir / "api_providers.json").write_text(
            json.dumps({"version": "1.0", "last_updated": "2025-11-04T00:00:00Z", "providers": []})
        )

        # Load config
        loader = ConfigurationLoader(config_dir)
        config = loader.load_prompts()

        assert isinstance(config, PromptTemplatesConfig)
        assert len(config.contexts) == 1
        assert config.contexts[0].id == "test_prompt"

    def test_reload_all(self, tmp_path: Path) -> None:
        """Test reloading all configurations."""
        config_dir = tmp_path / "configs"
        config_dir.mkdir()

        # Create minimal valid configs
        (config_dir / "api_providers.json").write_text(
            json.dumps({"version": "1.0", "last_updated": "2025-11-04T00:00:00Z", "providers": []})
        )
        (config_dir / "prompt_templates.json").write_text(
            json.dumps({"version": "1.0", "contexts": [], "fallbacks": {}})
        )
        (config_dir / "tools.json").write_text(json.dumps({"version": "1.0", "tools": []}))

        loader = ConfigurationLoader(config_dir)

        # First load (will cache)
        loader.load_providers()
        loader.load_prompts()

        # Reload all
        providers, prompts, tools = loader.reload_all()

        assert isinstance(providers, APIProvidersConfig)
        assert isinstance(prompts, PromptTemplatesConfig)
        from src.config.tool_models import ToolsConfig

        assert isinstance(tools, ToolsConfig)


class TestProviderRegistry:
    """Tests for ProviderRegistry."""

    def test_register_and_get_provider(self) -> None:
        """Test registering and retrieving providers."""
        registry = ProviderRegistry()

        # Create test provider
        from src.config.dynamic_models import AuthConfig, ProviderConfig

        provider = ProviderConfig(
            id="test",
            name="Test Provider",
            type=ProviderType.LLM,
            description="Test",
            base_url="https://api.test.com",
            auth=AuthConfig(scheme=AuthScheme.BEARER, env_var="TEST_KEY"),
        )

        registry.register(provider)

        retrieved = registry.get_provider("test")
        assert retrieved is not None
        assert retrieved.id == "test"

    def test_unregister_provider(self) -> None:
        """Test unregistering a provider."""
        registry = ProviderRegistry()

        from src.config.dynamic_models import ProviderConfig

        provider = ProviderConfig(
            id="test",
            name="Test",
            type=ProviderType.LLM,
            description="Test",
        )

        registry.register(provider)
        registry.unregister("test")

        assert registry.get_provider("test") is None

    def test_list_providers(self) -> None:
        """Test listing providers."""
        registry = ProviderRegistry()

        from src.config.dynamic_models import ProviderConfig

        provider1 = ProviderConfig(
            id="test1",
            name="Test 1",
            type=ProviderType.LLM,
            description="Test",
        )
        provider2 = ProviderConfig(
            id="test2",
            name="Test 2",
            type=ProviderType.TOOL,
            description="Test",
            enabled=False,
        )

        registry.register(provider1)
        registry.register(provider2)

        all_providers = registry.list_providers()
        assert len(all_providers) == 2
        assert "test1" in all_providers
        assert "test2" in all_providers

        enabled = registry.list_enabled_providers()
        assert len(enabled) == 1
        assert "test1" in enabled


class TestPromptRegistry:
    """Tests for PromptRegistry."""

    def test_register_and_get_prompt(self) -> None:
        """Test registering and retrieving prompts."""
        registry = PromptRegistry()

        from src.config.dynamic_models import PromptTemplate

        prompt = PromptTemplate(
            id="test",
            target="response_agent",
            description="Test prompt",
            prompt="You are a test assistant.",
        )

        registry.register(prompt)

        retrieved = registry.get_prompt("test")
        assert retrieved is not None
        assert retrieved.id == "test"

    def test_get_prompt_text(self) -> None:
        """Test getting prompt text."""
        registry = PromptRegistry()

        from src.config.dynamic_models import PromptTemplate

        prompt = PromptTemplate(
            id="test",
            target="response_agent",
            description="Test",
            prompt="Hello {name}, your age is {age}",
        )

        registry.register(prompt)

        text = registry.get_prompt_text("test", name="Alice", age="30")
        assert "Hello Alice" in text
        assert "your age is 30" in text

    def test_get_prompt_text_fallback(self) -> None:
        """Test fallback when prompt not found."""
        registry = PromptRegistry()
        registry.set_fallbacks({"missing_prompt": "Default prompt"})

        text = registry.get_prompt_text("nonexistent")
        assert text == "Default prompt"

    def test_get_prompts_by_target(self) -> None:
        """Test getting prompts by target."""
        registry = PromptRegistry()

        from src.config.dynamic_models import PromptTemplate

        prompt1 = PromptTemplate(
            id="test1",
            target="response_agent",
            description="Test",
            prompt="Test 1",
        )
        prompt2 = PromptTemplate(
            id="test2",
            target="knowledge_agent",
            description="Test",
            prompt="Test 2",
        )

        registry.register(prompt1)
        registry.register(prompt2)

        response_prompts = registry.get_prompts_by_target("response_agent")
        assert len(response_prompts) == 1
        assert response_prompts[0].id == "test1"
