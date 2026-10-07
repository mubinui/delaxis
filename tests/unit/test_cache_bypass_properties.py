"""Property-based testing for cache bypass behavior."""

from unittest.mock import Mock

from hypothesis import given, settings
from hypothesis import strategies as st

from src.config.cache_models import (
    AgentCacheConfig,
    CacheConfig,
    CacheType,
    LayerConfig,
    WorkflowCacheConfig,
)
from src.infrastructure.cache import RedisCache
from src.infrastructure.cache_manager import CacheManager


# Strategies for generating test data
@st.composite
def cache_key_strategy(draw):
    """Generate valid cache keys."""
    prefix = draw(st.sampled_from(["llm", "embedding", "session", "agent"]))
    suffix = draw(
        st.text(min_size=1, max_size=50, alphabet=st.characters(blacklist_characters="\x00\n\r"))
    )
    return f"{prefix}:{suffix}"


@st.composite
def cache_value_strategy(draw):
    """Generate cache values (JSON-serializable)."""
    return draw(
        st.one_of(
            st.text(max_size=100),
            st.integers(),
            st.floats(allow_nan=False, allow_infinity=False),
            st.lists(st.integers(), max_size=10),
            st.dictionaries(st.text(max_size=10), st.integers(), max_size=5),
        )
    )


def create_mock_redis_cache():
    """Create a mock Redis cache for testing."""
    mock_redis = Mock(spec=RedisCache)
    cache_storage = {}
    api_call_count = {"count": 0}

    def mock_get_json(key):
        api_call_count["count"] += 1
        return cache_storage.get(key)

    def mock_set_json(key, value, ttl=None):
        api_call_count["count"] += 1
        cache_storage[key] = value
        return True

    def mock_delete(key):
        api_call_count["count"] += 1
        if key in cache_storage:
            del cache_storage[key]
            return True
        return False

    def mock_exists(key):
        return key in cache_storage

    def mock_ping():
        return True

    mock_redis.get_json = mock_get_json
    mock_redis.set_json = mock_set_json
    mock_redis.delete = mock_delete
    mock_redis.exists = mock_exists
    mock_redis.ping = mock_ping
    mock_redis._storage = cache_storage
    mock_redis._api_calls = api_call_count

    return mock_redis


class TestCacheBypassProperties:
    """
    **Feature: industry-grade-orchestration, Property 8: Cache bypass behavior**
    **Validates: Requirements 3.4**

    Property: For any agent with cache disabled, LLM requests should bypass cache
    entirely and always make direct API calls.
    """

    @given(
        cache_key=cache_key_strategy(),
        cache_value=cache_value_strategy(),
        cache_type=st.sampled_from(list(CacheType)),
    )
    @settings(max_examples=100, deadline=None)
    def test_disabled_cache_bypasses_all_operations(self, cache_key, cache_value, cache_type):
        """
        Property: When cache is disabled for a specific layer, all cache operations
        (get and set) should be bypassed and return None/False.
        """
        # Create config with cache disabled for this type
        cache_config = CacheConfig(
            global_enabled=True, layers={cache_type: LayerConfig(enabled=False, ttl=3600)}
        )

        # Create mock Redis cache
        mock_redis = create_mock_redis_cache()

        # Create cache manager
        cache_manager = CacheManager(redis_cache=mock_redis, cache_config=cache_config)

        # Try to cache a value
        success = cache_manager.cache_response(
            cache_key=cache_key, value=cache_value, cache_type=cache_type
        )

        # Should fail because cache is disabled
        assert success is False

        # Try to retrieve
        result = cache_manager.get_cached_response(cache_key, cache_type)

        # Should be None
        assert result is None

        # Check metrics show bypasses
        metrics = cache_manager.get_cache_metrics()
        assert metrics["layers"][cache_type.value]["bypasses"] >= 2  # One for set, one for get
        assert metrics["layers"][cache_type.value]["sets"] == 0
        assert metrics["layers"][cache_type.value]["hits"] == 0

    @given(
        cache_key=cache_key_strategy(),
        cache_value=cache_value_strategy(),
        cache_type=st.sampled_from(
            [CacheType.LLM_RESPONSE, CacheType.EMBEDDING, CacheType.AGENT_RESULT]
        ),
        agent_id=st.text(min_size=1, max_size=20),
    )
    @settings(max_examples=100, deadline=None)
    def test_agent_override_disables_cache(self, cache_key, cache_value, cache_type, agent_id):
        """
        Property: When an agent has cache disabled via override, cache operations
        for that agent should be bypassed even if global cache is enabled.
        """
        # Create agent override config based on cache type
        agent_override_kwargs = {}
        if cache_type == CacheType.LLM_RESPONSE:
            agent_override_kwargs["llm_response"] = LayerConfig(enabled=False, ttl=0)
        elif cache_type == CacheType.EMBEDDING:
            agent_override_kwargs["embedding"] = LayerConfig(enabled=False, ttl=0)
        elif cache_type == CacheType.SESSION:
            agent_override_kwargs["session"] = LayerConfig(enabled=False, ttl=0)
        elif cache_type == CacheType.AGENT_RESULT:
            agent_override_kwargs["agent_result"] = LayerConfig(enabled=False, ttl=0)

        # Create config with global enabled but agent override disabled
        cache_config = CacheConfig(
            global_enabled=True,
            layers={cache_type: LayerConfig(enabled=True, ttl=3600)},
            agent_overrides={agent_id: AgentCacheConfig(**agent_override_kwargs)},
        )

        # Create mock Redis cache
        mock_redis = create_mock_redis_cache()

        # Create cache manager
        cache_manager = CacheManager(redis_cache=mock_redis, cache_config=cache_config)

        # Cache should be disabled for this agent
        assert cache_manager.is_cache_enabled(cache_type, agent_id=agent_id) is False

        # Try to cache with agent_id
        success = cache_manager.cache_response(
            cache_key=cache_key, value=cache_value, cache_type=cache_type, agent_id=agent_id
        )

        # Should fail
        assert success is False

        # Try to retrieve with agent_id
        result = cache_manager.get_cached_response(
            cache_key=cache_key, cache_type=cache_type, agent_id=agent_id
        )

        # Should be None
        assert result is None

        # But cache should work for other agents (no agent_id)
        success_global = cache_manager.cache_response(
            cache_key=cache_key, value=cache_value, cache_type=cache_type
        )

        # Should succeed for global
        assert success_global is True

    @given(
        cache_key=cache_key_strategy(),
        cache_value=cache_value_strategy(),
        cache_type=st.sampled_from(list(CacheType)),
        workflow_id=st.text(min_size=1, max_size=20),
    )
    @settings(max_examples=100, deadline=None)
    def test_workflow_override_disables_cache(
        self, cache_key, cache_value, cache_type, workflow_id
    ):
        """
        Property: When a workflow has cache disabled via override, cache operations
        for that workflow should be bypassed even if global cache is enabled.
        """
        # Create config with global enabled but workflow override disabled
        cache_config = CacheConfig(
            global_enabled=True,
            layers={cache_type: LayerConfig(enabled=True, ttl=3600)},
            workflow_overrides={
                workflow_id: WorkflowCacheConfig(
                    **{cache_type.value: LayerConfig(enabled=False, ttl=0)}
                )
            },
        )

        # Create mock Redis cache
        mock_redis = create_mock_redis_cache()

        # Create cache manager
        cache_manager = CacheManager(redis_cache=mock_redis, cache_config=cache_config)

        # Cache should be disabled for this workflow
        assert cache_manager.is_cache_enabled(cache_type, workflow_id=workflow_id) is False

        # Try to cache with workflow_id
        success = cache_manager.cache_response(
            cache_key=cache_key, value=cache_value, cache_type=cache_type, workflow_id=workflow_id
        )

        # Should fail
        assert success is False

        # Try to retrieve with workflow_id
        result = cache_manager.get_cached_response(
            cache_key=cache_key, cache_type=cache_type, workflow_id=workflow_id
        )

        # Should be None
        assert result is None

    @given(
        cache_key=cache_key_strategy(),
        cache_value=cache_value_strategy(),
        cache_type=st.sampled_from(
            [CacheType.LLM_RESPONSE, CacheType.EMBEDDING, CacheType.AGENT_RESULT]
        ),
        workflow_id=st.text(min_size=1, max_size=20),
        agent_id=st.text(min_size=1, max_size=20),
    )
    @settings(max_examples=100, deadline=None)
    def test_agent_override_takes_precedence_over_workflow(
        self, cache_key, cache_value, cache_type, workflow_id, agent_id
    ):
        """
        Property: Agent-level cache override should take precedence over workflow-level override.
        When workflow enables cache but agent disables it, cache should be bypassed.
        """
        # Create workflow and agent override configs based on cache type
        workflow_override_kwargs = {}
        agent_override_kwargs = {}

        if cache_type == CacheType.LLM_RESPONSE:
            workflow_override_kwargs["llm_response"] = LayerConfig(enabled=True, ttl=7200)
            agent_override_kwargs["llm_response"] = LayerConfig(enabled=False, ttl=0)
        elif cache_type == CacheType.EMBEDDING:
            workflow_override_kwargs["embedding"] = LayerConfig(enabled=True, ttl=7200)
            agent_override_kwargs["embedding"] = LayerConfig(enabled=False, ttl=0)
        elif cache_type == CacheType.SESSION:
            workflow_override_kwargs["session"] = LayerConfig(enabled=True, ttl=7200)
            agent_override_kwargs["session"] = LayerConfig(enabled=False, ttl=0)
        elif cache_type == CacheType.AGENT_RESULT:
            workflow_override_kwargs["agent_result"] = LayerConfig(enabled=True, ttl=7200)
            agent_override_kwargs["agent_result"] = LayerConfig(enabled=False, ttl=0)

        # Create config with workflow enabled but agent disabled
        cache_config = CacheConfig(
            global_enabled=True,
            layers={cache_type: LayerConfig(enabled=True, ttl=3600)},
            workflow_overrides={workflow_id: WorkflowCacheConfig(**workflow_override_kwargs)},
            agent_overrides={agent_id: AgentCacheConfig(**agent_override_kwargs)},
        )

        # Create mock Redis cache
        mock_redis = create_mock_redis_cache()

        # Create cache manager
        cache_manager = CacheManager(redis_cache=mock_redis, cache_config=cache_config)

        # Cache should be disabled for this agent (agent override wins)
        assert (
            cache_manager.is_cache_enabled(cache_type, workflow_id=workflow_id, agent_id=agent_id)
            is False
        )

        # Try to cache with both workflow_id and agent_id
        success = cache_manager.cache_response(
            cache_key=cache_key,
            value=cache_value,
            cache_type=cache_type,
            workflow_id=workflow_id,
            agent_id=agent_id,
        )

        # Should fail because agent override disables it
        assert success is False

        # But should work with just workflow_id (no agent_id)
        success_workflow = cache_manager.cache_response(
            cache_key=cache_key, value=cache_value, cache_type=cache_type, workflow_id=workflow_id
        )

        # Should succeed for workflow without agent override
        assert success_workflow is True

    @given(
        cache_key=cache_key_strategy(),
        cache_value=cache_value_strategy(),
        cache_type=st.sampled_from(list(CacheType)),
    )
    @settings(max_examples=100, deadline=None)
    def test_bypass_does_not_pollute_cache(self, cache_key, cache_value, cache_type):
        """
        Property: When cache is bypassed, no data should be written to the cache storage.
        """
        # Create config with cache disabled
        cache_config = CacheConfig(
            global_enabled=True, layers={cache_type: LayerConfig(enabled=False, ttl=3600)}
        )

        # Create mock Redis cache
        mock_redis = create_mock_redis_cache()

        # Create cache manager
        cache_manager = CacheManager(redis_cache=mock_redis, cache_config=cache_config)

        # Record initial storage state
        initial_storage_size = len(mock_redis._storage)

        # Try to cache (should be bypassed)
        cache_manager.cache_response(cache_key=cache_key, value=cache_value, cache_type=cache_type)

        # Storage should not have grown
        assert len(mock_redis._storage) == initial_storage_size

        # Verify the key is not in storage
        assert cache_key not in mock_redis._storage

    @given(
        cache_key=cache_key_strategy(),
        cache_value=cache_value_strategy(),
        cache_type=st.sampled_from(list(CacheType)),
    )
    @settings(max_examples=100, deadline=None)
    def test_global_disable_overrides_all_layers(self, cache_key, cache_value, cache_type):
        """
        Property: When global cache is disabled, all layer-specific settings should be
        ignored and cache should be bypassed.
        """
        # Create config with global disabled but layer enabled
        cache_config = CacheConfig(
            global_enabled=False,
            layers={cache_type: LayerConfig(enabled=True, ttl=3600, max_size=1000)},
        )

        # Create mock Redis cache
        mock_redis = create_mock_redis_cache()

        # Create cache manager
        cache_manager = CacheManager(redis_cache=mock_redis, cache_config=cache_config)

        # Cache should be disabled globally
        assert cache_manager.is_cache_enabled(cache_type) is False

        # Try to cache
        success = cache_manager.cache_response(
            cache_key=cache_key, value=cache_value, cache_type=cache_type
        )

        # Should fail
        assert success is False

        # Try to retrieve
        result = cache_manager.get_cached_response(cache_key, cache_type)

        # Should be None
        assert result is None

        # Verify bypasses are recorded
        metrics = cache_manager.get_cache_metrics()
        assert metrics["global_enabled"] is False
        assert metrics["layers"][cache_type.value]["bypasses"] >= 2
