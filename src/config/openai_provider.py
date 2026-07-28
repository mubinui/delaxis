"""
OpenAI SDK-based LLM Provider Configuration.

Uses OpenAI SDK directly with OpenRouter as the backend provider.
This replaces the LiteLLM-based implementation for better performance and reliability.
"""
import os
import asyncio
from dataclasses import dataclass, field
from typing import Optional, Literal, Dict, Any, List
from enum import Enum
import logging

from openai import AsyncOpenAI, OpenAI

logger = logging.getLogger(__name__)


class ProviderType(str, Enum):
    """Supported LLM provider types."""
    OPENROUTER = "openrouter"
    OPENAI = "openai"
    AZURE = "azure"
    LOCAL = "local"


@dataclass
class OpenAIProviderConfig:
    """Configuration for OpenAI SDK-based LLM providers."""
    
    # Provider selection
    provider: ProviderType = ProviderType.OPENROUTER
    model_name: str = "openai/gpt-oss-20b"
    
    # API settings
    api_key: Optional[str] = None
    base_url: str = "https://openrouter.ai/api/v1"
    
    # OpenRouter specific headers
    openrouter_site_url: Optional[str] = None
    openrouter_app_name: Optional[str] = None
    
    # Model configuration
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9
    
    # Timeout settings (in seconds)
    timeout: float = 60.0
    connect_timeout: float = 10.0
    
    # Debug settings
    debug_mode: bool = False
    
    # Cached clients
    _sync_client: Optional[OpenAI] = field(default=None, repr=False)
    _async_client: Optional[AsyncOpenAI] = field(default=None, repr=False)
    
    @classmethod
    def from_env(cls) -> "OpenAIProviderConfig":
        """Load configuration from environment variables."""
        provider_str = os.getenv("LLM_PROVIDER", "openrouter").lower()
        try:
            provider = ProviderType(provider_str)
        except ValueError:
            logger.warning(f"Invalid LLM_PROVIDER '{provider_str}', defaulting to openrouter")
            provider = ProviderType.OPENROUTER
        
        # Determine base URL and API key based on provider
        if provider == ProviderType.OPENROUTER:
            base_url = os.getenv("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")
            api_key = os.getenv("OPENROUTER_API_KEY")
        elif provider == ProviderType.OPENAI:
            base_url = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
            api_key = os.getenv("OPENAI_API_KEY")
        else:
            base_url = os.getenv("LLM_API_BASE", "http://localhost:8000/v1")
            api_key = os.getenv("LLM_API_KEY", "dummy")
        
        return cls(
            provider=provider,
            model_name=os.getenv("LLM_MODEL", "google/gemini-3.5-flash-lite"),
            api_key=api_key,
            base_url=base_url,
            openrouter_site_url=os.getenv("OR_SITE_URL"),
            openrouter_app_name=os.getenv("OR_APP_NAME"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
            top_p=float(os.getenv("LLM_TOP_P", "0.9")),
            timeout=float(os.getenv("LLM_TIMEOUT", "60.0")),
            connect_timeout=float(os.getenv("LLM_CONNECT_TIMEOUT", "10.0")),
            debug_mode=os.getenv("LLM_DEBUG", "false").lower() == "true",
        )
    
    def _get_extra_headers(self) -> Dict[str, str]:
        """Get extra headers for OpenRouter."""
        headers = {}
        if self.provider == ProviderType.OPENROUTER:
            if self.openrouter_site_url:
                headers["HTTP-Referer"] = self.openrouter_site_url
            if self.openrouter_app_name:
                headers["X-Title"] = self.openrouter_app_name
        return headers
    
    def get_sync_client(self) -> OpenAI:
        """Get or create synchronous OpenAI client."""
        if self._sync_client is None:
            self._sync_client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                default_headers=self._get_extra_headers(),
            )
        return self._sync_client
    
    def get_async_client(self) -> AsyncOpenAI:
        """Get or create asynchronous OpenAI client."""
        if self._async_client is None:
            self._async_client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                default_headers=self._get_extra_headers(),
            )
        return self._async_client
    
    def get_model_kwargs(self) -> Dict[str, Any]:
        """Get model kwargs for API calls."""
        return {
            "model": self.model_name,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
        }
    
    def test_connection_sync(self) -> bool:
        """
        Test connection to the LLM provider synchronously.
        
        Returns:
            True if connection successful, False otherwise.
        """
        try:
            client = self.get_sync_client()
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5,
            )
            logger.info(f"Successfully connected to {self.provider.value}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {self.provider.value}: {e}")
            return False
    
    async def test_connection_async(self) -> bool:
        """
        Test connection to the LLM provider asynchronously.
        
        Returns:
            True if connection successful, False otherwise.
        """
        try:
            client = self.get_async_client()
            response = await client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5,
            )
            logger.info(f"Successfully connected to {self.provider.value}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {self.provider.value}: {e}")
            return False
    
    def get_litellm_model_config(self) -> Dict[str, Any]:
        """
        Get configuration dict compatible with existing LiteLLM patterns.
        This allows gradual migration while keeping CrewAI LiteLlm wrapper working.
        """
        # For OpenRouter, use the openrouter/ prefix for LiteLLM
        if self.provider == ProviderType.OPENROUTER:
            model_string = f"openrouter/{self.model_name}"
        else:
            model_string = self.model_name
        
        return {
            "model": model_string,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
        }
    
    def get_model_string(self) -> str:
        """Get the model string for LiteLLM compatibility."""
        if self.provider == ProviderType.OPENROUTER:
            return f"openrouter/{self.model_name}"
        return self.model_name


# Global provider configuration instance
_openai_provider_config: Optional[OpenAIProviderConfig] = None


def get_openai_provider_config() -> OpenAIProviderConfig:
    """Get or create the global OpenAI provider configuration."""
    global _openai_provider_config
    if _openai_provider_config is None:
        _openai_provider_config = OpenAIProviderConfig.from_env()
        if _openai_provider_config.debug_mode:
            logger.info("OpenAI provider debug mode enabled")
    return _openai_provider_config


def reset_openai_provider_config():
    """Reset the global provider configuration. Useful for testing."""
    global _openai_provider_config
    _openai_provider_config = None
