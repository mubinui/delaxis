"""Pydantic models for agent configuration validation."""

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import AliasChoices, BaseModel, Field, model_validator

from src.config.behavior_models import AgentBehaviorConfig


class AgentType(str, Enum):
    """Type of agent."""

    CONVERSABLE = "conversable"
    RETRIEVE_USER_PROXY = "retrieve_user_proxy"
    GROUP_CHAT_MANAGER = "group_chat_manager"
    # CrewAI 0.4 agent types
    ASSISTANT = "assistant"
    CODE_EXECUTOR = "code_executor"
    CUSTOM = "custom"


class HumanInputMode(str, Enum):
    """Human input mode for agents."""

    ALWAYS = "ALWAYS"
    NEVER = "NEVER"
    TERMINATE = "TERMINATE"


class LLMConfig(BaseModel):
    """LLM configuration for an agent (v0.2 format)."""

    provider_id: str = Field(description="ID of the LLM provider from provider registry")
    model: str = Field(description="Model name to use (e.g., 'google/gemma-3-27b-it' or '@preset/my-preset')")
    preset: Optional[str] = Field(
        default=None,
        description="OpenRouter preset name (e.g., 'my-preset'). Can also use 'model@preset/name' syntax."
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: Optional[int] = Field(default=None, ge=1, description="Maximum tokens in response")
    cache_seed: Optional[int] = Field(default=None, description="Seed for caching (None disables CrewAI cache)")
    timeout: int = Field(default=120, ge=1, description="Request timeout in seconds")
    base_url: Optional[str] = Field(
        default=None, description="Custom API base URL (Ollama, LM Studio, vLLM, any OpenAI-compatible endpoint)"
    )
    api_key_env: Optional[str] = Field(
        default=None, description="Environment variable holding the API key for this agent's provider"
    )


class ModelClientConfig(BaseModel):
    """Configuration for CrewAI 0.4 model client.
    
    This is the v0.4 equivalent of LLMConfig, providing a more structured
    configuration for model clients with provider-specific settings.
    
    Based on the design document specification for Requirements 14.1.
    """
    
    provider_id: str = Field(
        description="Provider identifier (openai, azure, openrouter)"
    )
    model: str = Field(
        description="Model name (e.g., gpt-4, gpt-3.5-turbo)"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature"
    )
    timeout: int = Field(
        default=60,
        ge=1,
        description="Request timeout in seconds"
    )
    max_tokens: Optional[int] = Field(
        default=None,
        ge=1,
        description="Maximum tokens in response"
    )
    seed: Optional[int] = Field(
        default=None,
        description="Random seed for reproducibility"
    )
    # Provider-specific settings
    base_url: Optional[str] = Field(
        default=None,
        description="Base URL for API (required for OpenRouter)"
    )
    api_version: Optional[str] = Field(
        default=None,
        description="API version for Azure"
    )
    azure_deployment: Optional[str] = Field(
        default=None,
        description="Azure deployment name"
    )
    model_info: Optional[dict[str, Any]] = Field(
        default=None,
        description="Model capabilities info for OpenAI-compatible APIs"
    )
    api_key: Optional[str] = Field(
        default=None,
        description="API key for authentication (optional, can be from env)"
    )
    api_key_env: Optional[str] = Field(
        default=None,
        description="Environment variable holding the API key"
    )


class MemoryConfig(BaseModel):
    """Configuration for CrewAI 0.4 memory (RAG) integration.
    
    This configuration is used to set up memory for RAG agents,
    replacing the RetrieveUserProxyAgent pattern from v0.2.
    
    Based on the design document specification for Requirements 14.1.
    """
    
    type: str = Field(
        default="rag",
        description="Type of memory (currently only 'rag' is supported)"
    )
    vector_db: str = Field(
        default="chromadb",
        description="Vector database type (chromadb, qdrant, pgvector)"
    )
    collection_name: str = Field(
        description="Name of the vector database collection"
    )
    embedding_model: str = Field(
        default="all-mpnet-base-v2",
        description="Sentence transformer model for embeddings"
    )
    docs_path: Optional[List[str]] = Field(
        default=None,
        description="List of document paths or URLs to index"
    )
    chunk_token_size: int = Field(
        default=2000,
        ge=100,
        description="Token size for document chunks"
    )
    db_config: Optional[dict[str, Any]] = Field(
        default=None,
        description="Additional database-specific configuration"
    )


class RetrieveConfig(BaseModel):
    """Configuration for RetrieveUserProxyAgent."""

    task: str = Field(default="qa", description="Task type: 'qa', 'code', or 'default'")
    docs_path: list[str] = Field(description="List of document paths or URLs to index")
    chunk_token_size: int = Field(default=2000, ge=100, description="Token size for document chunks")
    vector_db: str = Field(default="chromadb", description="Vector database type")
    collection_name: str = Field(description="Name of the vector database collection")
    embedding_model: str = Field(
        default="all-mpnet-base-v2",
        description="Sentence transformer model for embeddings"
    )
    get_or_create: bool = Field(
        default=True,
        description="Whether to create collection if it doesn't exist"
    )
    db_config: Optional[dict[str, Any]] = Field(
        default=None,
        description="Additional database-specific configuration"
    )


class AgentConfig(BaseModel):
    """Configuration for creating an agent.
    
    Supports both CrewAI 0.2 (llm_config) and 0.4 (model_client_config) formats.
    The v0.4 fields are optional to maintain backward compatibility.
    """

    id: str = Field(pattern=r"^[a-z0-9_]+$", description="Unique agent identifier")
    type: AgentType = Field(description="Type of agent to create")
    name: str = Field(description="Display name for the agent")
    system_message: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("system_message", "instruction"),
        description="System message defining agent behavior (also accepts 'instruction' field)"
    )
    is_selector: bool = Field(
        default=False,
        description="Whether this agent is a selector/router agent"
    )
    model_config_override: Optional[dict] = Field(
        default=None,
        validation_alias=AliasChoices("model_config_override", "model_config"),
        description="Model configuration overrides (temperature, max_tokens, etc.)"
    )
    # v0.2 LLM configuration (kept for backward compatibility)
    llm_config: Optional[LLMConfig | bool] = Field(
        default=None,
        description="LLM configuration (v0.2 format), None for default, or False to disable LLM"
    )
    # v0.4 Model client configuration
    model_client_config: Optional[ModelClientConfig] = Field(
        default=None,
        validation_alias=AliasChoices("model_client_config", "model_client"),
        description="Model client configuration (v0.4 format) - alternative to llm_config"
    )
    # v0.4 Memory configuration for RAG agents
    memory_config: Optional[MemoryConfig] = Field(
        default=None,
        description="Memory configuration for RAG agents (v0.4 format)"
    )
    # v0.4 Tool reflection setting
    reflect_on_tool_use: bool = Field(
        default=True,
        description="Whether the agent should reflect on tool use results (v0.4)"
    )
    human_input_mode: HumanInputMode = Field(
        default=HumanInputMode.NEVER,
        description="When to request human input"
    )
    code_execution_config: Optional[dict[str, Any] | bool] = Field(
        default=False,
        description="Code execution configuration or False to disable"
    )
    tools: list[str] = Field(
        default_factory=list,
        description="List of tool IDs to register with this agent"
    )
    max_consecutive_auto_reply: int = Field(
        default=10,
        ge=0,
        description="Maximum consecutive auto-replies (0 means agent won't auto-reply)"
    )
    retrieve_config: Optional[RetrieveConfig] = Field(
        default=None,
        description="Retrieval configuration (required for retrieve_user_proxy agents, v0.2)"
    )
    description: Optional[str] = Field(
        default=None,
        description="Agent description for GroupChat/Team speaker selection"
    )
    behavior: Optional[AgentBehaviorConfig] = Field(
        default=None,
        description="Behavior configuration for output format, constraints, and validation"
    )
    
    # Versioning and metadata fields
    version: int = Field(
        default=1,
        ge=1,
        description="Configuration version number"
    )
    last_updated: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp of last configuration update"
    )

    def validate_config(self) -> None:
        """Validate agent configuration based on type.
        
        Note: For CrewAI 1.21.0, llm_config/model_client_config are optional.
        The provider_config is set globally via get_provider_config().
        """
        # For conversable agents, we no longer require llm_config/model_client_config
        # since CrewAI uses a global provider configuration
        # The validation is relaxed to support both CrewAI and CrewAI patterns
        if self.type == AgentType.CONVERSABLE:
            # CrewAI: model_config is optional, uses global provider
            # CrewAI: llm_config or model_client_config required
            # We accept either pattern
            pass
        
        if self.type == AgentType.RETRIEVE_USER_PROXY:
            if self.retrieve_config is None and self.memory_config is None:
                raise ValueError(f"Agent {self.id}: retrieve_user_proxy agents are missing the required retrieve_config or memory_config field")
        
        if self.type == AgentType.GROUP_CHAT_MANAGER:
            # Same relaxed validation for group chat managers
            pass
    
    def validate_v04_compatibility(self) -> List[str]:
        """Validate agent configuration for CrewAI 0.4 compatibility.
        
        Returns a list of validation errors. An empty list means the configuration
        is compatible with CrewAI 0.4.
        
        Based on the design document specification for Requirements 14.4.
        """
        errors: List[str] = []
        
        # Check for v0.4 agent types
        v04_types = {AgentType.ASSISTANT, AgentType.CODE_EXECUTOR, AgentType.CUSTOM}
        v02_types = {AgentType.CONVERSABLE, AgentType.RETRIEVE_USER_PROXY, AgentType.GROUP_CHAT_MANAGER}
        
        if self.type in v04_types:
            # v0.4 agent type - requires model_client_config
            if self.type == AgentType.ASSISTANT:
                if self.model_client_config is None and self.llm_config is None:
                    errors.append(
                        f"Agent {self.id}: assistant agents require model_client_config or llm_config"
                    )
            
            if self.type == AgentType.CODE_EXECUTOR:
                if self.code_execution_config is False or self.code_execution_config is None:
                    errors.append(
                        f"Agent {self.id}: code_executor agents require code_execution_config"
                    )
            
            if self.type == AgentType.CUSTOM:
                # Custom agents need system_message to define behavior
                if not self.system_message:
                    errors.append(
                        f"Agent {self.id}: custom agents require system_message"
                    )
        
        elif self.type in v02_types:
            # v0.2 agent type - check if it can be migrated
            if self.type == AgentType.RETRIEVE_USER_PROXY:
                if self.retrieve_config and not self.memory_config:
                    errors.append(
                        f"Agent {self.id}: retrieve_user_proxy should use memory_config for v0.4 compatibility. "
                        "Consider migrating to assistant type with memory_config."
                    )
        
        # Check for deprecated patterns
        if self.llm_config is not None and self.model_client_config is not None:
            errors.append(
                f"Agent {self.id}: both llm_config and model_client_config are set. "
                "Use only model_client_config for v0.4."
            )
        
        return errors
    
    def is_v04_compatible(self) -> bool:
        """Check if the agent configuration is compatible with CrewAI 0.4.
        
        Returns True if the configuration can be used with CrewAI 0.4 agents.
        """
        return len(self.validate_v04_compatibility()) == 0
    
    def get_effective_model_config(self) -> Optional[ModelClientConfig]:
        """Get the effective model client configuration.
        
        Returns model_client_config if set, otherwise converts llm_config
        to ModelClientConfig format.
        """
        if self.model_client_config is not None:
            return self.model_client_config
        
        if self.llm_config is not None and self.llm_config is not False:
            # Convert LLMConfig to ModelClientConfig
            return ModelClientConfig(
                provider_id=self.llm_config.provider_id,
                model=self.llm_config.model,
                temperature=self.llm_config.temperature,
                timeout=self.llm_config.timeout,
                max_tokens=self.llm_config.max_tokens,
                seed=self.llm_config.cache_seed,
                base_url=self.llm_config.base_url,
                api_key_env=self.llm_config.api_key_env,
            )
        
        return None


class AgentsConfig(BaseModel):
    """Root configuration for agents."""

    version: str = Field(description="Configuration version")
    agents: list[AgentConfig] = Field(description="List of agent configurations")

    @model_validator(mode='after')
    def validate_unique_agent_ids(self) -> "AgentsConfig":
        """Reject duplicate agent ids instead of silently shadowing them."""
        seen: set = set()
        duplicates: set = set()
        for agent in self.agents:
            if agent.id in seen:
                duplicates.add(agent.id)
            seen.add(agent.id)
        if duplicates:
            raise ValueError(f"Duplicate agent ids in configuration: {sorted(duplicates)}")
        return self

    def get_agent(self, agent_id: str) -> Optional[AgentConfig]:
        """Get agent configuration by ID."""
        return next((a for a in self.agents if a.id == agent_id), None)

    def validate_all(self) -> None:
        """Validate all agent configurations."""
        for agent in self.agents:
            agent.validate_config()
