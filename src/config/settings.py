"""Configuration management for the chatbot application."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OpenRouterConfig(BaseSettings):
    """OpenRouter API configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    api_key: str = Field(default="mock_api_key_for_testing", alias="OPENROUTER_API_KEY")
    model: str = Field(default="openai/gpt-oss-20b", alias="OPENROUTER_MODEL")
    base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )


class ApplicationConfig(BaseSettings):
    """Core application configuration."""

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    max_conversation_turns: int = Field(default=20, alias="MAX_CONVERSATION_TURNS")
    response_timeout_seconds: int = Field(default=30, alias="RESPONSE_TIMEOUT_SECONDS")
    otlp_endpoint: str | None = Field(default=None, alias="OTLP_ENDPOINT")
    # Port configuration — set APP_PORT to run on a different port (like n8n's N8N_PORT)
    api_port: int = Field(default=8000, alias="APP_PORT")
    # CORS — comma-separated list of allowed frontend origins, or "*" to allow all
    frontend_url: str = Field(default="*", alias="FRONTEND_URL")
    agent_runtime: str = Field(default="crewai", alias="AGENT_RUNTIME")
    crewai_storage_dir: str = Field(default="./data/.crewai", alias="CREWAI_STORAGE_DIR")
    crewai_memory_enabled: bool = Field(default=True, alias="CREWAI_MEMORY_ENABLED")
    crewai_process_default: str = Field(default="sequential", alias="CREWAI_PROCESS_DEFAULT")


class MemoryConfig(BaseSettings):
    """Memory and persistence configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    backend: str = Field(default="inmemory", alias="MEMORY_BACKEND")
    redis_url: str | None = Field(default=None, alias="REDIS_URL")
    database_url: str | None = Field(default=None, alias="DATABASE_URL")


class VectorDBConfig(BaseSettings):
    """Vector database configuration."""

    chromadb_path: str = Field(default="./data/chromadb", alias="CHROMADB_PATH")
    qdrant_url: str | None = Field(default=None, alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")
    qdrant_collection: str = Field(default="knowledge_base", alias="QDRANT_COLLECTION")
    pgvector_url: str | None = Field(default=None, alias="PGVECTOR_URL")


class MessageBrokerConfig(BaseSettings):
    """Message broker configuration."""

    rabbitmq_url: str | None = Field(default=None, alias="RABBITMQ_URL")
    max_connections: int = Field(default=10, alias="RABBITMQ_MAX_CONNECTIONS")
    max_channels: int = Field(default=100, alias="RABBITMQ_MAX_CHANNELS")


class TelemetryConfig(BaseSettings):
    """Observability and telemetry configuration."""

    enable_telemetry: bool = Field(default=True, alias="ENABLE_TELEMETRY")
    enable_metrics: bool = Field(default=True, alias="ENABLE_METRICS")
    prometheus_port: int = Field(default=9090, alias="PROMETHEUS_PORT")
    
    # Debug mode configuration
    debug_mode: bool = Field(default=False, alias="DEBUG_MODE")
    log_llm_prompts: bool = Field(default=False, alias="LOG_LLM_PROMPTS")
    log_llm_responses: bool = Field(default=False, alias="LOG_LLM_RESPONSES")
    log_agent_state: bool = Field(default=False, alias="LOG_AGENT_STATE")
    
    # Tracing configuration
    enable_tracing: bool = Field(default=True, alias="ENABLE_TRACING")
    trace_sampling_rate: float = Field(default=1.0, alias="TRACE_SAMPLING_RATE")


class SecurityConfig(BaseSettings):
    """Security and authentication configuration."""

    secret_key: str = Field(default="your-secret-key-change-in-production", alias="SECRET_KEY")
    algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    encryption_key: str | None = Field(default=None, alias="ENCRYPTION_KEY")
    
    # Rate limiting
    requests_per_minute: int = Field(default=60, alias="REQUESTS_PER_MINUTE")
    requests_per_hour: int = Field(default=1000, alias="REQUESTS_PER_HOUR")
    api_key_requests_per_minute: int = Field(default=100, alias="API_KEY_REQUESTS_PER_MINUTE")
    api_key_requests_per_hour: int = Field(default=5000, alias="API_KEY_REQUESTS_PER_HOUR")


class KeycloakConfig(BaseSettings):
    """Keycloak OIDC configuration with multi-realm support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    enabled: bool = Field(default=False, alias="KEYCLOAK_ENABLED")
    server_url: str = Field(default="http://localhost:8080", alias="KEYCLOAK_SERVER_URL")
    realm: str = Field(default="demo-realm", alias="KEYCLOAK_REALM")
    client_id: str = Field(default="frontend-client", alias="KEYCLOAK_CLIENT_ID")
    client_secret: str | None = Field(default=None, alias="KEYCLOAK_CLIENT_SECRET")
    admin_client_id: str = Field(default="admin-client", alias="KEYCLOAK_ADMIN_CLIENT_ID")
    admin_client_secret: str | None = Field(default=None, alias="KEYCLOAK_ADMIN_CLIENT_SECRET")

    verify_audience: bool = Field(default=True, alias="KEYCLOAK_VERIFY_AUDIENCE")
    jwks_cache_ttl: int = Field(default=3600, alias="KEYCLOAK_JWKS_CACHE_TTL")

    @property
    def jwks_uri(self) -> str:
        """JWKS endpoint for token signature verification."""
        return f"{self.server_url}/realms/{self.realm}/protocol/openid-connect/certs"

    @property
    def token_endpoint(self) -> str:
        """Token endpoint for client_credentials grant."""
        return f"{self.server_url}/realms/{self.realm}/protocol/openid-connect/token"

    @property
    def issuer(self) -> str:
        """Expected token issuer."""
        return f"{self.server_url}/realms/{self.realm}"
    
    def get_jwks_uri(self, realm: str | None = None) -> str:
        """Get JWKS URI for a specific realm."""
        realm_name = realm or self.realm
        return f"{self.server_url}/realms/{realm_name}/protocol/openid-connect/certs"
    
    def get_token_endpoint(self, realm: str | None = None) -> str:
        """Get token endpoint for a specific realm."""
        realm_name = realm or self.realm
        return f"{self.server_url}/realms/{realm_name}/protocol/openid-connect/token"
    
    def get_issuer(self, realm: str | None = None) -> str:
        """Get issuer for a specific realm."""
        realm_name = realm or self.realm
        return f"{self.server_url}/realms/{realm_name}"
    
    def get_admin_secret(self, realm: str | None = None) -> str | None:
        """Get admin client secret for a specific realm."""
        return self.admin_client_secret


class VoiceConfig(BaseSettings):
    """Live voice limits.

    A realtime audio session bills for as long as it is open, and the voice
    WebSocket does not pass through the HTTP middleware stack that rate-limits
    everything else — so these caps are the only thing standing between a stuck
    (or hostile) client and an unbounded bill. Defaults are deliberately tight.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    enabled: bool = Field(default=True, alias="DELAXIS_VOICE_ENABLED")
    max_session_seconds: int = Field(default=300, alias="DELAXIS_VOICE_MAX_SESSION_SECONDS")
    max_concurrent: int = Field(default=4, alias="DELAXIS_VOICE_MAX_CONCURRENT")
    ticket_ttl_seconds: int = Field(default=30, alias="DELAXIS_VOICE_TICKET_TTL_SECONDS")


class ExternalServicesConfig(BaseSettings):
    """External service endpoints configuration (Service1, Service2)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Service1 configuration (user-authenticated calls)
    service1_base_url: str = Field(default="http://localhost:8001", alias="SERVICE1_BASE_URL")
    service1_api_path: str = Field(default="/api/v1", alias="SERVICE1_API_PATH")
    service1_timeout: int = Field(default=30, alias="SERVICE1_TIMEOUT")
    service1_enabled: bool = Field(default=False, alias="SERVICE1_ENABLED")

    # Service2 configuration (admin-authenticated calls)
    service2_base_url: str = Field(default="http://localhost:8002", alias="SERVICE2_BASE_URL")
    service2_api_path: str = Field(default="/api/v1", alias="SERVICE2_API_PATH")
    service2_timeout: int = Field(default=30, alias="SERVICE2_TIMEOUT")
    service2_enabled: bool = Field(default=False, alias="SERVICE2_ENABLED")

    # RAG Pipeline configuration
    rag_pipeline_base_url: str = Field(default="http://localhost:8003", alias="RAG_PIPELINE_BASE_URL")
    rag_pipeline_timeout: int = Field(default=60, alias="RAG_PIPELINE_TIMEOUT")
    rag_pipeline_enabled: bool = Field(default=True, alias="RAG_PIPELINE_ENABLED")
    rag_pipeline_api_key: str | None = Field(default=None, alias="RAG_PIPELINE_API_KEY")
    rag_pipeline_default_collection: str = Field(default="knowledge_base", alias="RAG_PIPELINE_DEFAULT_COLLECTION")


class Settings(BaseSettings):
    """Root settings container."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    openrouter: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    app: ApplicationConfig = Field(default_factory=ApplicationConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    vector_db: VectorDBConfig = Field(default_factory=VectorDBConfig)
    message_broker: MessageBrokerConfig = Field(default_factory=MessageBrokerConfig)
    keycloak: KeycloakConfig = Field(default_factory=KeycloakConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    external_services: ExternalServicesConfig = Field(default_factory=ExternalServicesConfig)
    
    @property
    def database_url(self) -> str:
        """Database URL for platform persistence (SQLite by default)."""
        return self.memory.database_url or "sqlite:///./data/delaxis.db"


# Global settings instance
_settings: Settings | None = None


def get_settings(reload: bool = False) -> Settings:
    """Get or initialize the global settings instance."""
    global _settings
    if _settings is None or reload:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset the global settings instance (useful for testing or reloading config)."""
    global _settings
    _settings = None
