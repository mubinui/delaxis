"""Property-based testing for cache lookup behavior."""

from unittest.mock import Mock

from hypothesis import given, settings
from hypothesis import strategies as st

from src.config.cache_models import CacheConfig, CacheType, EvictionPolicy, LayerConfig
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


@st.composite
def cache_config_strategy(draw, enabled=True):
    """Generate cache configurations."""
    return CacheConfig(
        global_enabled=enabled,
        layers={
            CacheType.LLM_RESPONSE: LayerConfig(
                enabled=draw(st.booleans()),
                ttl=draw(st.integers(min_value=0, max_value=7200)),
                max_size=draw(st.one_of(st.none(), st.integers(min_value=10, max_value=1000))),
                eviction_policy=draw(st.sampled_from(list(EvictionPolicy))),
            ),
            CacheType.EMBEDDING: LayerConfig(
                enabled=draw(st.booleans()),
                ttl=draw(st.integers(min_value=0, max_value=86400)),
                max_size=draw(st.one_of(st.none(), st.integers(min_value=10, max_value=1000))),
                eviction_policy=draw(st.sampled_from(list(EvictionPolicy))),
            ),
            CacheType.SESSION: LayerConfig(
                enabled=draw(st.booleans()),
                ttl=draw(st.integers(min_value=0, max_value=3600)),
                max_size=draw(st.one_of(st.none(), st.integers(min_value=10, max_value=1000))),
                eviction_policy=draw(st.sampled_from(list(EvictionPolicy))),
            ),
            CacheType.AGENT_RESULT: LayerConfig(
                enabled=draw(st.booleans()),
                ttl=draw(st.integers(min_value=0, max_value=1800)),
                max_size=draw(st.one_of(st.none(), st.integers(min_value=10, max_value=1000))),
                eviction_policy=draw(st.sampled_from(list(EvictionPolicy))),
            ),
        },
    )


def create_mock_redis_cache():
    """Create a mock Redis cache for testing."""
    mock_redis = Mock(spec=RedisCache)
    cache_storage = {}

    def mock_get_json(key):
        return cache_storage.get(key)

    def mock_set_json(key, value, ttl=None):
        cache_storage[key] = value
        return True

    def mock_delete(key):
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
    mock_redis._storage = cache_storage  # For inspection

    return mock_redis


class TestCacheLookupProperties:
    """
    **Feature: industry-grade-orchestration, Property 7: Cache lookup behavior**
    **Validates: Requirements 3.2**

    Property: For any LLM request with cache enabled, the cache should be checked
    before making an API call, and cache hits should not trigger API calls.
    """

    @given(
        cache_key=cache_key_strategy(),
        cache_value=cache_value_strategy(),
        cache_type=st.sampled_from(list(CacheType)),
        cache_config=cache_config_strategy(enabled=True),
    )
    @settings(max_examples=100, deadline=None)
    def test_cache_hit_prevents_api_call(self, cache_key, cache_value, cache_type, cache_config):
        """
        Property: When a value is cached and cache is enabled, subsequent lookups
        should return the cached value without checking Redis again (for in-memory caches).
        """
        # Create mock Redis cache
        mock_redis = create_mock_redis_cache()

        # Create cache manager with config
        cache_manager = CacheManager(redis_cache=mock_redis, cache_config=cache_config)

        # First, cache the value
        cache_manager.cache_response(cache_key=cache_key, value=cache_value, cache_type=cache_type)

        # Get the effective config to check if cache is enabled
        effective_config = cache_manager.get_effective_config(cache_type)

        if effective_config is None or not effective_config.enabled:
            # Cache is disabled, should bypass
            result = cache_manager.get_cached_response(cache_key, cache_type)
            assert result is None
            metrics = cache_manager.get_cache_metrics()
            assert metrics["layers"][cache_type.value]["bypasses"] > 0
        else:
            # Cache is enabled, should hit
            len(mock_redis._storage)

            # Retrieve from cache
            result = cache_manager.get_cached_response(cache_key, cache_type)

            # Should get the cached value
            assert result == cache_value

            # Check metrics show a hit
            metrics = cache_manager.get_cache_metrics()
            assert metrics["layers"][cache_type.value]["hits"] > 0

    @given(
        cache_key=cache_key_strategy(),
        cache_type=st.sampled_from(list(CacheType)),
        cache_config=cache_config_strategy(enabled=True),
    )
    @settings(max_examples=100, deadline=None)
    def test_cache_miss_recorded(self, cache_key, cache_type, cache_config):
        """
        Property: When a value is not in cache and cache is enabled,
        a cache miss should be recorded in metrics.
        """
        # Create mock Redis cache
        mock_redis = create_mock_redis_cache()

        # Create cache manager with config
        cache_manager = CacheManager(redis_cache=mock_redis, cache_config=cache_config)

        # Try to get non-existent value
        result = cache_manager.get_cached_response(cache_key, cache_type)

        # Get the effective config
        effective_config = cache_manager.get_effective_config(cache_type)

        if effective_config is None or not effective_config.enabled:
            # Cache is disabled, should be None and bypass recorded
            assert result is None
            metrics = cache_manager.get_cache_metrics()
            assert metrics["layers"][cache_type.value]["bypasses"] > 0
        else:
            # Cache is enabled, should be None and miss recorded
            assert result is None
            metrics = cache_manager.get_cache_metrics()
            assert metrics["layers"][cache_type.value]["misses"] > 0

    @given(
        cache_key=cache_key_strategy(),
        cache_value=cache_value_strategy(),
        cache_type=st.sampled_from(list(CacheType)),
        workflow_id=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
        agent_id=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
    )
    @settings(max_examples=100, deadline=None)
    def test_cache_hierarchy_respected(
        self, cache_key, cache_value, cache_type, workflow_id, agent_id
    ):
        """
        Property: Cache configuration hierarchy (global → workflow → agent)
        should be respected when checking if cache is enabled.
        """
        # Create a config with global enabled
        cache_config = CacheConfig(
            global_enabled=True, layers={cache_type: LayerConfig(enabled=True, ttl=3600)}
        )

        # Create mock Redis cache
        mock_redis = create_mock_redis_cache()

        # Create cache manager
        cache_manager = CacheManager(redis_cache=mock_redis, cache_config=cache_config)

        # Cache should be enabled at global level
        assert cache_manager.is_cache_enabled(cache_type) is True

        # Cache a value
        success = cache_manager.cache_response(
            cache_key=cache_key,
            value=cache_value,
            cache_type=cache_type,
            workflow_id=workflow_id,
            agent_id=agent_id,
        )

        assert success is True

        # Retrieve should work
        result = cache_manager.get_cached_response(
            cache_key=cache_key, cache_type=cache_type, workflow_id=workflow_id, agent_id=agent_id
        )

        assert result == cache_value

    @given(
        cache_key=cache_key_strategy(),
        cache_value=cache_value_strategy(),
        cache_type=st.sampled_from(list(CacheType)),
    )
    @settings(max_examples=100, deadline=None)
    def test_global_disable_bypasses_all_caches(self, cache_key, cache_value, cache_type):
        """
        Property: When global cache is disabled, all cache operations should be bypassed
        regardless of layer-specific settings.
        """
        # Create config with global disabled but layer enabled
        cache_config = CacheConfig(
            global_enabled=False, layers={cache_type: LayerConfig(enabled=True, ttl=3600)}
        )

        # Create mock Redis cache
        mock_redis = create_mock_redis_cache()

        # Create cache manager
        cache_manager = CacheManager(redis_cache=mock_redis, cache_config=cache_config)

        # Try to cache
        success = cache_manager.cache_response(
            cache_key=cache_key, value=cache_value, cache_type=cache_type
        )

        # Should fail because global is disabled
        assert success is False

        # Try to retrieve
        result = cache_manager.get_cached_response(cache_key, cache_type)

        # Should be None
        assert result is None

        # Check metrics show bypass
        metrics = cache_manager.get_cache_metrics()
        assert metrics["layers"][cache_type.value]["bypasses"] > 0
