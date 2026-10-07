"""Pydantic models for API provider configuration."""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class APIProviderCreateRequest(BaseModel):
    """Request to create an API provider."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$", description="Unique provider identifier")
    name: str = Field(min_length=1, description="Provider display name")
    type: str = Field(description="Provider type (llm, tool, api)")
    description: str = Field(min_length=1, description="Provider description")
    base_url: str | None = Field(default=None, description="Base URL for API")
    api_key: str | None = Field(default=None, description="API key for authentication")
    api_key_env: str | None = Field(
        default=None, description="Env var holding the API key (stored as auth.env_var)"
    )
    litellm_prefix: str | None = Field(
        default=None,
        description="Native LiteLLM route prefix; leave unset for OpenAI-compatible endpoints",
    )
    models: list[dict[str, Any]] | None = Field(
        default=None, description='Model entries, e.g. [{"name": "qwen-plus"}]'
    )
    enabled: bool = Field(default=True, description="Whether provider is enabled")
    config: dict[str, Any] = Field(default_factory=dict, description="Additional configuration")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate provider type."""
        valid_types = ["llm", "tool", "api"]
        if v not in valid_types:
            raise ValueError(f"Provider type must be one of: {', '.join(valid_types)}")
        return v


class APIProviderUpdateRequest(BaseModel):
    """Request to update an API provider."""

    name: str | None = None
    type: str | None = None
    description: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    litellm_prefix: str | None = None
    models: list[dict[str, Any]] | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str | None) -> str | None:
        """Validate provider type."""
        if v is None:
            return v
        valid_types = ["llm", "tool", "api"]
        if v not in valid_types:
            raise ValueError(f"Provider type must be one of: {', '.join(valid_types)}")
        return v


class APIProviderResponse(BaseModel):
    """Response containing API provider information."""

    id: str
    name: str
    type: str
    description: str
    base_url: str | None = None
    api_key_masked: str | None = None
    api_key_env: str | None = None
    litellm_prefix: str | None = None
    models: list[dict[str, Any]] | None = None
    enabled: bool
    config: dict[str, Any]
    version: int | None = None
    etag: str | None = None
    last_updated: str | None = None


class ConnectionTestResponse(BaseModel):
    """Response from testing API provider connection."""

    success: bool
    message: str
    details: dict[str, Any] | None = None


def mask_api_key(api_key: str | None) -> str | None:
    """
    Mask API key showing only last 4 characters.

    Args:
        api_key: API key to mask

    Returns:
        Masked API key or None if input is None
    """
    if api_key is None or len(api_key) == 0:
        return None

    if len(api_key) <= 4:
        return "*" * len(api_key)

    return "*" * (len(api_key) - 4) + api_key[-4:]
