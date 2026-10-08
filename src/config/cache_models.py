"""Multi-layer cache configuration with TTL and eviction policies."""

from enum import StrEnum

from pydantic import BaseModel, Field


class CacheType(StrEnum):
    """Type of cache layer."""

    LLM_RESPONSE = "llm_response"
    EMBEDDING = "embedding"
    SESSION = "session"
    AGENT_RESULT = "agent_result"


class EvictionPolicy(StrEnum):
    """Cache eviction policy."""

    LRU = "LRU"  # Least Recently Used
    LFU = "LFU"  # Least Frequently Used
    TTL = "TTL"  # Time To Live only


class LayerConfig(BaseModel):
    """Configuration for a specific cache layer."""

    enabled: bool = Field(default=True, description="Whether this cache layer is enabled")
    ttl: int = Field(default=3600, ge=0, description="Time to live in seconds (0 = no expiration)")
    max_size: int | None = Field(
        default=None, ge=1, description="Maximum cache size (None = unlimited)"
    )
    eviction_policy: EvictionPolicy = Field(
        default=EvictionPolicy.LRU, description="Eviction policy"
    )


class WorkflowCacheConfig(BaseModel):
    """Cache configuration overrides for a specific workflow."""

    llm_response: LayerConfig | None = Field(
        default=None, description="LLM response cache override"
    )
    embedding: LayerConfig | None = Field(default=None, description="Embedding cache override")
    session: LayerConfig | None = Field(default=None, description="Session cache override")
    agent_result: LayerConfig | None = Field(
        default=None, description="Agent result cache override"
    )


class AgentCacheConfig(BaseModel):
    """Cache configuration overrides for a specific agent."""

    llm_response: LayerConfig | None = Field(
        default=None, description="LLM response cache override"
    )
    embedding: LayerConfig | None = Field(default=None, description="Embedding cache override")
    agent_result: LayerConfig | None = Field(
        default=None, description="Agent result cache override"
    )


class CacheConfig(BaseModel):
    """Root cache configuration with multi-layer support."""

    global_enabled: bool = Field(default=True, description="Global cache enable/disable")
    layers: dict[CacheType, LayerConfig] = Field(
        default_factory=lambda: {
            CacheType.LLM_RESPONSE: LayerConfig(
                enabled=True, ttl=3600, eviction_policy=EvictionPolicy.LRU
            ),
            CacheType.EMBEDDING: LayerConfig(
                enabled=True, ttl=86400, eviction_policy=EvictionPolicy.LFU
            ),
            CacheType.SESSION: LayerConfig(
                enabled=True, ttl=1800, eviction_policy=EvictionPolicy.TTL
            ),
            CacheType.AGENT_RESULT: LayerConfig(enabled=False),
        },
        description="Configuration for each cache layer",
    )
    workflow_overrides: dict[str, WorkflowCacheConfig] = Field(
        default_factory=dict, description="Workflow-specific cache overrides"
    )
    agent_overrides: dict[str, AgentCacheConfig] = Field(
        default_factory=dict, description="Agent-specific cache overrides"
    )

    def is_cache_enabled(
        self, cache_type: CacheType, workflow_id: str | None = None, agent_id: str | None = None
    ) -> bool:
        """
        Check if cache is enabled for a specific type, workflow, and agent.

        Args:
            cache_type: Type of cache to check
            workflow_id: Optional workflow ID for workflow-specific override
            agent_id: Optional agent ID for agent-specific override

        Returns:
            True if cache is enabled, False otherwise
        """
        if not self.global_enabled:
            return False

        # Check agent override first (most specific)
        if agent_id and agent_id in self.agent_overrides:
            agent_override = self.agent_overrides[agent_id]
            layer_override = getattr(agent_override, cache_type.value, None)
            if layer_override is not None:
                return bool(layer_override.enabled)

        # Check workflow override
        if workflow_id and workflow_id in self.workflow_overrides:
            workflow_override = self.workflow_overrides[workflow_id]
            layer_override = getattr(workflow_override, cache_type.value, None)
            if layer_override is not None:
                return bool(layer_override.enabled)

        # Fall back to global layer config
        if cache_type in self.layers:
            return self.layers[cache_type].enabled

        return False

    def get_effective_layer_config(
        self, cache_type: CacheType, workflow_id: str | None = None, agent_id: str | None = None
    ) -> LayerConfig | None:
        """
        Get the effective cache layer configuration considering hierarchy.

        Args:
            cache_type: Type of cache layer
            workflow_id: Optional workflow ID for workflow-specific override
            agent_id: Optional agent ID for agent-specific override

        Returns:
            Effective LayerConfig or None if cache is disabled
        """
        if not self.is_cache_enabled(cache_type, workflow_id, agent_id):
            return None

        # Start with global config
        config = self.layers.get(cache_type)
        if config is None:
            return None

        # Apply workflow override if present
        if workflow_id and workflow_id in self.workflow_overrides:
            workflow_override = self.workflow_overrides[workflow_id]
            layer_override = getattr(workflow_override, cache_type.value, None)
            if layer_override is not None:
                # Merge configs (override takes precedence)
                config = LayerConfig(
                    enabled=layer_override.enabled,
                    ttl=layer_override.ttl,
                    max_size=layer_override.max_size
                    if layer_override.max_size is not None
                    else config.max_size,
                    eviction_policy=layer_override.eviction_policy,
                )

        # Apply agent override if present (highest priority)
        if agent_id and agent_id in self.agent_overrides:
            agent_override = self.agent_overrides[agent_id]
            layer_override = getattr(agent_override, cache_type.value, None)
            if layer_override is not None:
                config = LayerConfig(
                    enabled=layer_override.enabled,
                    ttl=layer_override.ttl,
                    max_size=layer_override.max_size
                    if layer_override.max_size is not None
                    else config.max_size,
                    eviction_policy=layer_override.eviction_policy,
                )

        return config
