"""
LLM Provider Configuration Module

Supports multiple LLM providers (OpenRouter, vLLM) with automatic fallback.
Uses OpenAI SDK directly for OpenRouter (no LiteLLM).
"""
import os
import subprocess
from dataclasses import dataclass
from typing import Optional
from enum import Enum
import logging

from src.config.model_capabilities import ModelCapabilities, infer_model_capabilities

logger = logging.getLogger(__name__)


class ProviderType(str, Enum):
    """Supported LLM provider types."""
    OPENROUTER = "openrouter"
    VLLM = "vllm"
    OLLAMA = "ollama"


@dataclass
class ProviderConfig:
    """Configuration for LLM providers with fallback support."""
    
    # Provider selection
    provider: ProviderType = ProviderType.OPENROUTER
    fallback_provider: Optional[ProviderType] = None
    model_name: str = "openai/gpt-oss-20b"
    
    # OpenRouter settings
    openrouter_api_key: Optional[str] = None
    openrouter_api_base: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: Optional[str] = None
    openrouter_app_name: Optional[str] = None
    
    # OpenRouter Preset (https://openrouter.ai/docs/features/presets)
    # Use a saved preset configuration from OpenRouter dashboard
    # Format: "preset-slug" (will be used as @preset/preset-slug)
    openrouter_preset: Optional[str] = None
    
    # OpenRouter Provider Routing (https://openrouter.ai/docs/provider-routing)
    openrouter_provider_order: Optional[list] = None  # ["Fireworks", "Together", "DeepInfra"]
    openrouter_provider_allow_fallbacks: bool = True
    openrouter_provider_require_parameters: bool = False
    openrouter_provider_data_collection: Optional[str] = None  # "allow" or "deny"
    openrouter_provider_ignore: Optional[list] = None  # Providers to skip
    openrouter_provider_quantizations: Optional[list] = None  # ["bf16", "fp8", "int4"]
    
    # OpenRouter Transforms
    openrouter_transforms: Optional[list] = None  # ["middle-out"] for context compression
    
    # OpenRouter Multi-model fallback
    openrouter_fallback_models: Optional[list] = None  # ["openai/gpt-4o", "anthropic/claude-3"]
    openrouter_route: str = "fallback"  # "fallback" for model fallback routing
    
    # vLLM settings
    vllm_api_base: str = "http://localhost:8000"
    vllm_api_key: Optional[str] = None
    vllm_use_gcloud_auth: bool = False
    
    # Ollama settings
    ollama_api_base: str = "http://localhost:11434"
    
    # Caching settings
    enable_cache: bool = True
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: Optional[str] = None
    
    # Model configuration
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9
    
    # Debug settings
    debug_mode: bool = False
    
    @classmethod
    def from_env(cls) -> "ProviderConfig":
        """Load configuration from environment variables."""
        provider_str = os.getenv("LLM_PROVIDER", "openrouter").lower()
        try:
            provider = ProviderType(provider_str)
        except ValueError:
            logger.warning(f"Invalid LLM_PROVIDER '{provider_str}', defaulting to openrouter")
            provider = ProviderType.OPENROUTER
        
        fallback_str = os.getenv("LLM_FALLBACK_PROVIDER")
        fallback_provider = None
        if fallback_str:
            try:
                fallback_provider = ProviderType(fallback_str.lower())
            except ValueError:
                logger.warning(f"Invalid LLM_FALLBACK_PROVIDER '{fallback_str}', ignoring")
        
        # Helper to parse comma-separated list from env
        def parse_list(env_var: str) -> Optional[list]:
            val = os.getenv(env_var)
            if val:
                return [v.strip() for v in val.split(",") if v.strip()]
            return None
        
        return cls(
            provider=provider,
            fallback_provider=fallback_provider,
            model_name=os.getenv("LLM_MODEL", "google/gemini-3.5-flash-lite"),
            
            # OpenRouter
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
            openrouter_api_base=os.getenv("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1"),
            openrouter_site_url=os.getenv("OR_SITE_URL"),
            openrouter_app_name=os.getenv("OR_APP_NAME"),
            
            # OpenRouter Preset (use saved configuration from dashboard)
            # Set OR_PRESET=my-preset to use @preset/my-preset
            openrouter_preset=os.getenv("OR_PRESET"),
            
            # OpenRouter Provider Routing (overrides preset settings if both set)
            openrouter_provider_order=parse_list("OR_PROVIDER_ORDER"),
            openrouter_provider_allow_fallbacks=os.getenv("OR_PROVIDER_ALLOW_FALLBACKS", "true").lower() == "true",
            openrouter_provider_require_parameters=os.getenv("OR_PROVIDER_REQUIRE_PARAMS", "false").lower() == "true",
            openrouter_provider_data_collection=os.getenv("OR_PROVIDER_DATA_COLLECTION"),
            openrouter_provider_ignore=parse_list("OR_PROVIDER_IGNORE"),
            openrouter_provider_quantizations=parse_list("OR_PROVIDER_QUANTIZATIONS"),
            openrouter_transforms=parse_list("OR_TRANSFORMS"),
            openrouter_fallback_models=parse_list("OR_FALLBACK_MODELS"),
            openrouter_route=os.getenv("OR_ROUTE", "fallback"),
            
            # vLLM
            vllm_api_base=os.getenv("VLLM_API_BASE", "http://localhost:8000"),
            vllm_api_key=os.getenv("VLLM_API_KEY"),
            vllm_use_gcloud_auth=os.getenv("VLLM_USE_GCLOUD_AUTH", "false").lower() == "true",
            
            # Ollama
            ollama_api_base=os.getenv("OLLAMA_API_BASE", "http://localhost:11434"),
            
            # Cache
            enable_cache=os.getenv("ENABLE_CACHE", "true").lower() == "true",
            redis_host=os.getenv("REDIS_HOST", "localhost"),
            redis_port=int(os.getenv("REDIS_PORT", "6379")),
            redis_password=os.getenv("REDIS_PASSWORD"),
            
            # Model params
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
            top_p=float(os.getenv("LLM_TOP_P", "0.9")),
            
            # Debug
            debug_mode=os.getenv("DEBUG_LLM", "false").lower() == "true",
        )
    
    def _get_gcloud_auth_token(self) -> Optional[str]:
        """Get Google Cloud authentication token for vLLM endpoints."""
        try:
            token = subprocess.check_output(
                ["gcloud", "auth", "print-identity-token", "-q"],
                stderr=subprocess.DEVNULL
            ).decode().strip()
            return token
        except Exception as e:
            logger.warning(f"Failed to get gcloud auth token: {e}")
            return None
    
    def get_model_config(
        self, 
        provider: Optional[ProviderType] = None
    ) -> dict:
        """
        Get model configuration dictionary for the LLM client.
        
        Args:
            provider: Override the default provider. Used for fallback.
        
        Returns:
            Dictionary with model configuration
        """
        target_provider = provider or self.provider
        config = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
        }
        
        if target_provider == ProviderType.OPENROUTER:
            # Set environment variables for OpenRouter
            if self.openrouter_api_key:
                os.environ["OPENROUTER_API_KEY"] = self.openrouter_api_key
            os.environ["OPENROUTER_API_BASE"] = self.openrouter_api_base
            
            if self.openrouter_site_url:
                os.environ["OR_SITE_URL"] = self.openrouter_site_url
            if self.openrouter_app_name:
                os.environ["OR_APP_NAME"] = self.openrouter_app_name
            
            # Determine model string based on preset configuration
            # Priority: preset > model_name
            if self.openrouter_preset:
                # Using OpenRouter preset - format: @preset/preset-slug
                preset_slug = self.openrouter_preset.lstrip("@preset/")
                config["model"] = f"openrouter/@preset/{preset_slug}"
                logger.info(f"Using OpenRouter preset: @preset/{preset_slug}")
            else:
                config["model"] = f"openrouter/{self.model_name}"
            
            # Add OpenRouter settings via extra_body (passed through to OpenRouter API)
            extra_body = {}
            
            # Provider routing preferences (can override preset settings)
            provider_prefs = {}
            if self.openrouter_provider_order:
                provider_prefs["order"] = self.openrouter_provider_order
            if not self.openrouter_provider_allow_fallbacks:
                provider_prefs["allow_fallbacks"] = False
            if self.openrouter_provider_require_parameters:
                provider_prefs["require_parameters"] = True
            if self.openrouter_provider_data_collection:
                provider_prefs["data_collection"] = self.openrouter_provider_data_collection
            if self.openrouter_provider_ignore:
                provider_prefs["ignore"] = self.openrouter_provider_ignore
            if self.openrouter_provider_quantizations:
                provider_prefs["quantizations"] = self.openrouter_provider_quantizations
            
            if provider_prefs:
                extra_body["provider"] = provider_prefs
            
            # Transforms (e.g., middle-out context compression)
            if self.openrouter_transforms:
                extra_body["transforms"] = self.openrouter_transforms
            
            # Multi-model fallback routing
            if self.openrouter_fallback_models:
                extra_body["models"] = [self.model_name] + self.openrouter_fallback_models
                extra_body["route"] = self.openrouter_route
            
            if extra_body:
                config["extra_body"] = extra_body
                logger.info(f"OpenRouter presets: {list(extra_body.keys())}")
            
            logger.info(f"Configured OpenRouter with model: {config['model']}")
        
        elif target_provider == ProviderType.VLLM:
            # vLLM configuration
            config["model"] = f"hosted_vllm/{self.model_name}"
            config["api_base"] = self.vllm_api_base
            
            # Authentication
            if self.vllm_use_gcloud_auth:
                token = self._get_gcloud_auth_token()
                if token:
                    config["extra_headers"] = {"Authorization": f"Bearer {token}"}
                    logger.info("Using gcloud authentication for vLLM")
            elif self.vllm_api_key:
                config["api_key"] = self.vllm_api_key
            
            logger.info(f"Configured vLLM at {self.vllm_api_base} with model: {config['model']}")
        
        elif target_provider == ProviderType.OLLAMA:
            # Ollama configuration
            os.environ["OLLAMA_API_BASE"] = self.ollama_api_base
            model_short = self.model_name.split("/")[-1]
            config["model"] = f"ollama_chat/{model_short}"
            logger.info(f"Configured Ollama with model: {config['model']}")
        
        return config
    
    def get_model_string(self, provider: Optional[ProviderType] = None) -> str:
        """Get the model string for the specified provider."""
        config = self.get_model_config(provider)
        return config["model"]

    def get_model_capabilities(
        self,
        model_name: Optional[str] = None,
        provider: Optional[ProviderType] = None,
    ) -> ModelCapabilities:
        """Get inferred capability flags for the active or supplied model."""
        return infer_model_capabilities(
            model_name or self.model_name,
            (provider or self.provider).value,
        )
    
    def get_openrouter_presets(self) -> dict:
        """
        Get a summary of configured OpenRouter presets.
        
        Returns:
            Dictionary with configured preset information for debugging/display.
        """
        if self.provider != ProviderType.OPENROUTER:
            return {"enabled": False, "reason": "Not using OpenRouter provider"}
        
        presets = {"enabled": True}
        
        if self.openrouter_provider_order:
            presets["provider_order"] = self.openrouter_provider_order
        if not self.openrouter_provider_allow_fallbacks:
            presets["allow_fallbacks"] = False
        if self.openrouter_provider_require_parameters:
            presets["require_parameters"] = True
        if self.openrouter_provider_data_collection:
            presets["data_collection"] = self.openrouter_provider_data_collection
        if self.openrouter_provider_ignore:
            presets["ignore_providers"] = self.openrouter_provider_ignore
        if self.openrouter_provider_quantizations:
            presets["quantizations"] = self.openrouter_provider_quantizations
        if self.openrouter_transforms:
            presets["transforms"] = self.openrouter_transforms
        if self.openrouter_fallback_models:
            presets["fallback_models"] = self.openrouter_fallback_models
            presets["route"] = self.openrouter_route
        
        return presets
    
    def configure_cache(self):
        """Configure caching (placeholder for future implementation)."""
        if not self.enable_cache:
            logger.info("Caching disabled")
            return
        
        # Future: implement caching with Redis or in-memory
        logger.info("Using default in-memory caching")
    
    def enable_debug(self):
        """Enable debug mode to see raw API requests."""
        if self.debug_mode:
            logger.info("Debug mode enabled - will log API requests")
            # Set logging level for detailed output
            logging.getLogger("openai").setLevel(logging.DEBUG)
            logging.getLogger("httpx").setLevel(logging.DEBUG)
    
    def test_model_connection(self, provider: Optional[ProviderType] = None) -> bool:
        """
        Test connection to the LLM provider using OpenAI SDK.
        
        Note: This is a synchronous blocking call. For faster startup,
        consider using test_model_connection_async() or skipping the test.
        
        Args:
            provider: Provider to test. Defaults to primary provider.
        
        Returns:
            True if connection successful, False otherwise.
        """
        # Skip connection test if SKIP_LLM_CONNECTION_TEST is set
        if os.getenv("SKIP_LLM_CONNECTION_TEST", "true").lower() == "true":
            logger.info("Skipping LLM connection test (SKIP_LLM_CONNECTION_TEST=true)")
            return True
            
        target_provider = provider or self.provider
        try:
            from openai import OpenAI
            
            if target_provider == ProviderType.OPENROUTER:
                client = OpenAI(
                    api_key=self.openrouter_api_key,
                    base_url=self.openrouter_api_base
                )
                model = self.model_name
            elif target_provider == ProviderType.VLLM:
                client = OpenAI(
                    api_key=self.vllm_api_key or "EMPTY",
                    base_url=f"{self.vllm_api_base}/v1"
                )
                model = self.model_name
            elif target_provider == ProviderType.OLLAMA:
                client = OpenAI(
                    api_key="ollama",
                    base_url=f"{self.ollama_api_base}/v1"
                )
                model = self.model_name.split("/")[-1]
            else:
                logger.warning(f"Unknown provider: {target_provider}")
                return True
            
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10
            )
            logger.info(f"Successfully connected to {target_provider.value}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {target_provider.value}: {e}")
            return False
    
    def check_function_calling_support(self) -> bool:
        """Check if the current model supports function calling."""
        supports_fc = self.get_model_capabilities().tool_calling
        logger.info(f"Model {self.model_name} - Function calling: {supports_fc}")
        return supports_fc


# Global provider configuration instance
_provider_config: Optional[ProviderConfig] = None


def get_provider_config() -> ProviderConfig:
    """Get or create the global provider configuration."""
    global _provider_config
    if _provider_config is None:
        _provider_config = ProviderConfig.from_env()
        _provider_config.configure_cache()
        _provider_config.enable_debug()
    return _provider_config


def reset_provider_config():
    """Reset the global provider configuration. Useful for testing."""
    global _provider_config
    _provider_config = None
