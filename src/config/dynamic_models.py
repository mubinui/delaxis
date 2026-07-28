"""Pydantic models for dynamic configuration validation."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProviderType(str, Enum):
    """Type of provider."""

    LLM = "llm"
    TOOL = "tool"
    SEARCH = "search"
    DATABASE = "database"
    API = "api"


class AuthScheme(str, Enum):
    """Authentication scheme."""

    BEARER = "bearer"
    API_KEY = "api_key"
    BASIC = "basic"
    OAUTH2 = "oauth2"
    NONE = "none"


class AuthConfig(BaseModel):
    """Authentication configuration for a provider."""

    scheme: AuthScheme
    env_var: str | None = Field(None, description="Environment variable containing credentials")
    header_name: str | None = Field(None, description="Custom header name for API key")
    required: bool = Field(True, description="Whether the provider refuses unauthenticated requests")


class ModelCapability(str, Enum):
    """LLM model capabilities."""

    CHAT = "chat"
    REASONING = "reasoning"
    EMBEDDING = "embedding"
    VISION = "vision"
    FUNCTION_CALLING = "function_calling"
    STRUCTURED_OUTPUTS = "structured_outputs"


class ModelPricing(BaseModel):
    """Pricing information for a model."""

    input_per_million_tokens: float = Field(ge=0)
    output_per_million_tokens: float = Field(ge=0)
    currency: str = Field(default="USD")


class ModelConfig(BaseModel):
    """LLM model configuration."""

    name: str
    default: bool = False
    capabilities: list[ModelCapability] = []
    pricing: ModelPricing | None = None
    max_tokens: int | None = Field(None, ge=1)
    temperature: float | None = Field(None, ge=0, le=2)
    litellm_string: str | None = Field(None, description="Exact LiteLLM model string, overrides prefixing")
    context_window: int | None = Field(None, ge=1)
    max_output_tokens: int | None = Field(None, ge=1)


class RequestDefaults(BaseModel):
    """Default request configuration."""

    timeout_seconds: int = Field(default=120, ge=1)
    max_retries: int = Field(default=2, ge=0)
    headers: dict[str, str] = Field(default_factory=dict)


class ProviderConfig(BaseModel):
    """Configuration for an API provider."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1)
    type: ProviderType
    description: str = Field(default="")
    enabled: bool = Field(default=True)

    # LLM-specific fields
    base_url: str | None = None
    base_url_env: str | None = Field(None, description="Env var that overrides base_url")
    default_base_url: str | None = Field(None, description="Fallback base URL when env is unset")
    litellm_prefix: str | None = Field(
        None, description="Native LiteLLM route prefix (e.g. 'openai', 'gemini', 'ollama'); unset = OpenAI-compatible via base_url"
    )
    litellm_base_url: str | None = Field(
        None, description="api_base handed to LiteLLM in native-prefix mode (self-hosted providers)"
    )
    api_key: str | None = Field(None, description="Inline API key; wins over auth.env_var")
    auth: AuthConfig | None = None
    models: list[ModelConfig] = Field(default_factory=list)
    request_defaults: RequestDefaults | None = None

    # Tool-specific fields
    library: str | None = Field(None, description="Python library name")
    entrypoint: str | None = Field(None, description="Import path like 'module:Class'")
    settings: dict[str, Any] = Field(default_factory=dict)


class APIProvidersConfig(BaseModel):
    """Root configuration for API providers."""

    version: str
    last_updated: datetime
    providers: list[ProviderConfig]

    def get_provider(self, provider_id: str) -> ProviderConfig | None:
        """Get provider by ID."""
        return next((p for p in self.providers if p.id == provider_id), None)

    def get_enabled_providers(self) -> list[ProviderConfig]:
        """Get all enabled providers."""
        return [p for p in self.providers if p.enabled]


class PromptTemplate(BaseModel):
    """A prompt template."""

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    target: str = Field(description="Target agent type (e.g., 'response_agent')")
    description: str
    prompt: str
    variables: list[str] = Field(default_factory=list, description="Template variables")
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptTemplatesConfig(BaseModel):
    """Root configuration for prompt templates."""

    version: str
    contexts: list[PromptTemplate]
    fallbacks: dict[str, str] = Field(default_factory=dict)

    def get_prompt(self, prompt_id: str) -> PromptTemplate | None:
        """Get a prompt template by ID."""
        return next((p for p in self.contexts if p.id == prompt_id), None)

    def get_prompts_by_target(self, target: str) -> list[PromptTemplate]:
        """Get all prompts for a specific target."""
        return [p for p in self.contexts if p.target == target]
