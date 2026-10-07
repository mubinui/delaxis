"""Multi-layer cache management with configuration hierarchy."""

import logging
from collections import OrderedDict
from datetime import UTC, datetime
from threading import Lock
from typing import Any
from uuid import UUID

from src.config.cache_models import CacheConfig, CacheType, EvictionPolicy, LayerConfig
from src.infrastructure.cache import RedisCache
from src.infrastructure.embedding_cache import EmbeddingCache
from src.infrastructure.llm_cache import LLMCacheMonitor
from src.infrastructure.session_cache import SessionCache
from src.utils.time import parse_utc

logger = logging.getLogger(__name__)


class CacheInvalidationStrategy:
    """Base class for cache invalidation strategies."""

    def should_invalidate(self, key: str, metadata: dict[str, Any]) -> bool:
        """Determine if a cache entry should be invalidated.

        Args:
            key: Cache key
            metadata: Cache entry metadata

        Returns:
            True if entry should be invalidated, False otherwise
        """
        raise NotImplementedError


class TimeBasedInvalidation(CacheInvalidationStrategy):
    """Invalidate cache entries based on age."""

    def __init__(self, max_age_seconds: int):
        """Initialize time-based invalidation.

        Args:
            max_age_seconds: Maximum age in seconds before invalidation
        """
        self.max_age_seconds = max_age_seconds

    def should_invalidate(self, key: str, metadata: dict[str, Any]) -> bool:
        """Check if entry is older than max age."""
        created_at = metadata.get("created_at")
        if not created_at:
            return False

        try:
            created_time = parse_utc(created_at)
            age = (datetime.now(UTC) - created_time).total_seconds()
            return age > self.max_age_seconds
        except (ValueError, TypeError):
            return False


class LRUCache:
    """Simple LRU cache implementation for in-memory caching."""

    def __init__(self, max_size: int):
        """Initialize LRU cache.

        Args:
            max_size: Maximum number of items in cache
        """
        self.max_size = max_size
        self.cache: OrderedDict = OrderedDict()
        self.lock = Lock()

    def get(self, key: str) -> Any | None:
        """Get item from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None
        """
        with self.lock:
            if key in self.cache:
                # Move to end (most recently used)
                self.cache.move_to_end(key)
                return self.cache[key]
            return None

    def set(self, key: str, value: Any) -> None:
        """Set item in cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        with self.lock:
            if key in self.cache:
                # Update and move to end
                self.cache.move_to_end(key)
            self.cache[key] = value

            # Evict oldest if over max size
            if len(self.cache) > self.max_size:
                self.cache.popitem(last=False)

    def delete(self, key: str) -> bool:
        """Delete item from cache.

        Args:
            key: Cache key

        Returns:
            True if deleted, False if not found
        """
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                return True
            return False

    def clear(self) -> int:
        """Clear all items from cache.

        Returns:
            Number of items cleared
        """
        with self.lock:
            count = len(self.cache)
            self.cache.clear()
            return count


class LFUCache:
    """Simple LFU cache implementation for in-memory caching."""

    def __init__(self, max_size: int):
        """Initialize LFU cache.

        Args:
            max_size: Maximum number of items in cache
        """
        self.max_size = max_size
        self.cache: dict[str, Any] = {}
        self.frequencies: dict[str, int] = {}
        self.lock = Lock()

    def get(self, key: str) -> Any | None:
        """Get item from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None
        """
        with self.lock:
            if key in self.cache:
                self.frequencies[key] = self.frequencies.get(key, 0) + 1
                return self.cache[key]
            return None

    def set(self, key: str, value: Any) -> None:
        """Set item in cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        with self.lock:
            if key in self.cache:
                self.cache[key] = value
                self.frequencies[key] = self.frequencies.get(key, 0) + 1
            else:
                if len(self.cache) >= self.max_size:
                    # Evict least frequently used
                    lfu_key = min(self.frequencies, key=self.frequencies.get)
                    del self.cache[lfu_key]
                    del self.frequencies[lfu_key]

                self.cache[key] = value
                self.frequencies[key] = 1

    def delete(self, key: str) -> bool:
        """Delete item from cache.

        Args:
            key: Cache key

        Returns:
            True if deleted, False if not found
        """
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                del self.frequencies[key]
                return True
            return False

    def clear(self) -> int:
        """Clear all items from cache.

        Returns:
            Number of items cleared
        """
        with self.lock:
            count = len(self.cache)
            self.cache.clear()
            self.frequencies.clear()
            return count


class CacheManager:
    """
    Manager for coordinating cache operations across different cache types.

    Handles:
    - Multi-layer cache configuration with hierarchy (global → workflow → agent)
    - Cache enable/disable at different levels
    - TTL configuration per cache type
    - Multiple eviction policies (LRU, LFU, TTL)
    - Cache metrics and monitoring
    - Cache invalidation strategies
    - Cache warming
    """

    def __init__(
        self,
        redis_cache: RedisCache,
        cache_config: CacheConfig | None = None,
        session_cache: SessionCache | None = None,
        embedding_cache: EmbeddingCache | None = None,
        llm_cache_monitor: LLMCacheMonitor | None = None,
    ):
        """Initialize cache manager.

        Args:
            redis_cache: Redis cache client
            cache_config: Cache configuration with hierarchy support
            session_cache: Optional session cache
            embedding_cache: Optional embedding cache
            llm_cache_monitor: Optional LLM cache monitor
        """
        self.redis_cache = redis_cache
        self.cache_config = cache_config or CacheConfig()
        self.session_cache = session_cache or SessionCache(redis_cache)
        self.embedding_cache = embedding_cache or EmbeddingCache(redis_cache)
        self.llm_cache_monitor = llm_cache_monitor

        # In-memory caches for LRU/LFU policies
        self._memory_caches: dict[str, Any] = {}
        self._cache_metrics: dict[str, dict[str, int]] = {
            cache_type.value: {"hits": 0, "misses": 0, "sets": 0, "deletes": 0, "bypasses": 0}
            for cache_type in CacheType
        }

        logger.info(
            f"Cache manager initialized with config: global_enabled={self.cache_config.global_enabled}"
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
        return self.cache_config.is_cache_enabled(cache_type, workflow_id, agent_id)

    def get_effective_config(
        self, cache_type: CacheType, workflow_id: str | None = None, agent_id: str | None = None
    ) -> LayerConfig | None:
        """
        Get the effective cache configuration considering hierarchy.

        Args:
            cache_type: Type of cache layer
            workflow_id: Optional workflow ID for workflow-specific override
            agent_id: Optional agent ID for agent-specific override

        Returns:
            Effective LayerConfig or None if cache is disabled
        """
        return self.cache_config.get_effective_layer_config(cache_type, workflow_id, agent_id)

    def _get_memory_cache(self, cache_key: str, layer_config: LayerConfig) -> Any | None:
        """Get or create in-memory cache based on eviction policy.

        Args:
            cache_key: Unique key for this cache instance
            layer_config: Layer configuration with eviction policy

        Returns:
            In-memory cache instance or None
        """
        if layer_config.max_size is None:
            return None

        if cache_key not in self._memory_caches:
            if layer_config.eviction_policy == EvictionPolicy.LRU:
                self._memory_caches[cache_key] = LRUCache(layer_config.max_size)
            elif layer_config.eviction_policy == EvictionPolicy.LFU:
                self._memory_caches[cache_key] = LFUCache(layer_config.max_size)
            else:
                # TTL policy doesn't need in-memory cache
                return None

        return self._memory_caches.get(cache_key)

    def get_cached_response(
        self,
        cache_key: str,
        cache_type: CacheType,
        workflow_id: str | None = None,
        agent_id: str | None = None,
    ) -> Any | None:
        """
        Get cached response with configuration hierarchy support.

        Args:
            cache_key: Cache key
            cache_type: Type of cache
            workflow_id: Optional workflow ID
            agent_id: Optional agent ID

        Returns:
            Cached value or None
        """
        # Check if cache is enabled
        if not self.is_cache_enabled(cache_type, workflow_id, agent_id):
            self._cache_metrics[cache_type.value]["bypasses"] += 1
            logger.debug(f"Cache bypassed for {cache_type.value}: disabled")
            return None

        # Get effective configuration
        layer_config = self.get_effective_config(cache_type, workflow_id, agent_id)
        if layer_config is None:
            self._cache_metrics[cache_type.value]["bypasses"] += 1
            return None

        # Check in-memory cache first (for LRU/LFU)
        memory_cache_key = f"{cache_type.value}:{workflow_id or 'global'}:{agent_id or 'global'}"
        memory_cache = self._get_memory_cache(memory_cache_key, layer_config)
        if memory_cache:
            value = memory_cache.get(cache_key)
            if value is not None:
                self._cache_metrics[cache_type.value]["hits"] += 1
                logger.debug(f"Memory cache hit for {cache_type.value}: {cache_key}")
                return value

        # Check Redis cache
        value = self.redis_cache.get_json(cache_key)
        if value is not None:
            self._cache_metrics[cache_type.value]["hits"] += 1
            logger.debug(f"Redis cache hit for {cache_type.value}: {cache_key}")

            # Update memory cache if applicable
            if memory_cache:
                memory_cache.set(cache_key, value)

            return value

        self._cache_metrics[cache_type.value]["misses"] += 1
        logger.debug(f"Cache miss for {cache_type.value}: {cache_key}")
        return None

    def cache_response(
        self,
        cache_key: str,
        value: Any,
        cache_type: CacheType,
        workflow_id: str | None = None,
        agent_id: str | None = None,
        ttl: int | None = None,
    ) -> bool:
        """
        Cache response with configuration hierarchy support.

        Args:
            cache_key: Cache key
            value: Value to cache
            cache_type: Type of cache
            workflow_id: Optional workflow ID
            agent_id: Optional agent ID
            ttl: Optional TTL override

        Returns:
            True if cached successfully, False otherwise
        """
        # Check if cache is enabled
        if not self.is_cache_enabled(cache_type, workflow_id, agent_id):
            self._cache_metrics[cache_type.value]["bypasses"] += 1
            logger.debug(f"Cache bypassed for {cache_type.value}: disabled")
            return False

        # Get effective configuration
        layer_config = self.get_effective_config(cache_type, workflow_id, agent_id)
        if layer_config is None:
            self._cache_metrics[cache_type.value]["bypasses"] += 1
            return False

        # Use configured TTL if not overridden
        effective_ttl = ttl if ttl is not None else layer_config.ttl
        if effective_ttl == 0:
            effective_ttl = None  # No expiration

        # Cache in Redis
        success = self.redis_cache.set_json(cache_key, value, effective_ttl)
        if success:
            self._cache_metrics[cache_type.value]["sets"] += 1
            logger.debug(f"Cached {cache_type.value}: {cache_key} (ttl={effective_ttl})")

            # Update memory cache if applicable
            memory_cache_key = (
                f"{cache_type.value}:{workflow_id or 'global'}:{agent_id or 'global'}"
            )
            memory_cache = self._get_memory_cache(memory_cache_key, layer_config)
            if memory_cache:
                memory_cache.set(cache_key, value)

        return success

    def update_cache_config(self, new_config: CacheConfig) -> None:
        """
        Update cache configuration at runtime.

        Args:
            new_config: New cache configuration
        """
        logger.info("Updating cache configuration")
        self.cache_config = new_config

        # Clear memory caches to apply new policies
        self._memory_caches.clear()
        logger.info("Cache configuration updated and memory caches cleared")

    def invalidate_session(self, session_id: UUID) -> bool:
        """Invalidate session cache.

        Args:
            session_id: Session identifier

        Returns:
            True if invalidated, False otherwise
        """
        logger.info(f"Invalidating session cache: {session_id}")
        return self.session_cache.delete(session_id)

    def invalidate_sessions_by_user(self, user_id: str) -> int:
        """Invalidate all sessions for a user.

        Args:
            user_id: User identifier

        Returns:
            Number of sessions invalidated
        """
        logger.info(f"Invalidating sessions for user: {user_id}")

        count = 0
        session_ids = self.session_cache.get_all_session_ids()

        for session_id in session_ids:
            metadata = self.session_cache.get_session_metadata(session_id)
            if metadata and metadata.get("metadata", {}).get("user_id") == user_id:
                if self.session_cache.delete(session_id):
                    count += 1

        logger.info(f"Invalidated {count} sessions for user {user_id}")
        return count

    def invalidate_embedding(self, content: str, model: str = "default") -> bool:
        """Invalidate embedding cache.

        Args:
            content: Text content
            model: Embedding model name

        Returns:
            True if invalidated, False otherwise
        """
        logger.debug(f"Invalidating embedding cache (model={model})")
        return self.embedding_cache.delete(content, model)

    def invalidate_embeddings_by_model(self, model: str) -> int:
        """Invalidate all embeddings for a specific model.

        Args:
            model: Embedding model name

        Returns:
            Number of embeddings invalidated
        """
        logger.info(f"Invalidating embeddings for model: {model}")

        count = 0
        hashes = self.embedding_cache.get_all_embedding_hashes()

        for content_hash in hashes:
            data = self.embedding_cache.get_by_hash(content_hash)
            if data and data.get("model") == model:
                if self.embedding_cache.delete_by_hash(content_hash):
                    count += 1

        logger.info(f"Invalidated {count} embeddings for model {model}")
        return count

    def invalidate_all_sessions(self) -> int:
        """Invalidate all session caches.

        Returns:
            Number of sessions invalidated
        """
        logger.warning("Invalidating all session caches")
        return self.session_cache.clear_all_sessions()

    def invalidate_all_embeddings(self) -> int:
        """Invalidate all embedding caches.

        Returns:
            Number of embeddings invalidated
        """
        logger.warning("Invalidating all embedding caches")
        return self.embedding_cache.clear_all_embeddings()

    def invalidate_all_caches(self) -> dict[str, int]:
        """Invalidate all caches.

        Returns:
            Dictionary with counts of invalidated entries by cache type
        """
        logger.warning("Invalidating all caches")

        return {
            "sessions": self.invalidate_all_sessions(),
            "embeddings": self.invalidate_all_embeddings(),
        }

    def warm_session_cache(
        self,
        session_ids: list[UUID],
        fetch_callback: Any,
    ) -> int:
        """Warm session cache by pre-loading sessions.

        Args:
            session_ids: List of session IDs to warm
            fetch_callback: Callback function to fetch session data

        Returns:
            Number of sessions warmed
        """
        logger.info(f"Warming session cache for {len(session_ids)} sessions")

        count = 0
        for session_id in session_ids:
            try:
                # Check if already cached
                if self.session_cache.exists(session_id):
                    continue

                # Fetch session data
                session = fetch_callback(session_id)
                if session:
                    # Cache the session
                    if self.session_cache.set(session):
                        count += 1
            except Exception as e:
                logger.error(
                    f"Failed to warm session cache for {session_id}: {e}",
                    exc_info=True,
                )

        logger.info(f"Warmed {count} sessions in cache")
        return count

    def warm_embedding_cache(
        self,
        contents: list[str],
        fetch_callback: Any,
        model: str = "default",
    ) -> int:
        """Warm embedding cache by pre-computing embeddings.

        Args:
            contents: List of text contents to warm
            fetch_callback: Callback function to fetch embeddings
            model: Embedding model name

        Returns:
            Number of embeddings warmed
        """
        logger.info(f"Warming embedding cache for {len(contents)} contents (model={model})")

        count = 0
        for content in contents:
            try:
                # Check if already cached
                if self.embedding_cache.exists(content, model):
                    continue

                # Fetch embedding
                embedding = fetch_callback(content, model)
                if embedding:
                    # Cache the embedding
                    if self.embedding_cache.set(content, embedding, model):
                        count += 1
            except Exception as e:
                logger.error(
                    f"Failed to warm embedding cache: {e}",
                    exc_info=True,
                )

        logger.info(f"Warmed {count} embeddings in cache")
        return count

    def get_cache_metrics(self) -> dict[str, Any]:
        """Get metrics for all caches including hit rates and configuration status.

        Returns:
            Dictionary with cache metrics
        """
        metrics = {
            "global_enabled": self.cache_config.global_enabled,
            "layers": {},
            "sessions": {
                "total": len(self.session_cache.get_all_session_ids()),
                "ttl_seconds": self.session_cache.session_ttl,
            },
            "embeddings": self.embedding_cache.get_cache_stats(),
        }

        # Add per-layer metrics
        for cache_type in CacheType:
            layer_metrics = self._cache_metrics[cache_type.value].copy()
            total_requests = layer_metrics["hits"] + layer_metrics["misses"]
            hit_rate = (layer_metrics["hits"] / total_requests * 100) if total_requests > 0 else 0.0

            layer_config = self.cache_config.layers.get(cache_type)

            metrics["layers"][cache_type.value] = {
                "enabled": layer_config.enabled if layer_config else False,
                "ttl": layer_config.ttl if layer_config else 0,
                "eviction_policy": layer_config.eviction_policy.value if layer_config else None,
                "max_size": layer_config.max_size if layer_config else None,
                "hits": layer_metrics["hits"],
                "misses": layer_metrics["misses"],
                "bypasses": layer_metrics["bypasses"],
                "sets": layer_metrics["sets"],
                "deletes": layer_metrics["deletes"],
                "hit_rate": round(hit_rate, 2),
            }

        # Add LLM cache metrics if monitor is available
        if self.llm_cache_monitor:
            llm_metrics = self.llm_cache_monitor.get_metrics()
            metrics["llm"] = llm_metrics.to_dict()

        # Add Redis connection status
        metrics["redis"] = {
            "connected": self.redis_cache.ping(),
        }

        # Add configuration overrides count
        metrics["overrides"] = {
            "workflows": len(self.cache_config.workflow_overrides),
            "agents": len(self.cache_config.agent_overrides),
        }

        return metrics

    def apply_invalidation_strategy(
        self,
        strategy: CacheInvalidationStrategy,
        cache_type: str = "all",
    ) -> dict[str, int]:
        """Apply invalidation strategy to caches.

        Args:
            strategy: Invalidation strategy to apply
            cache_type: Type of cache to apply to ("sessions", "embeddings", "all")

        Returns:
            Dictionary with counts of invalidated entries by cache type
        """
        logger.info(f"Applying invalidation strategy to {cache_type} cache(s)")

        results = {}

        # Apply to session cache
        if cache_type in ("sessions", "all"):
            count = 0
            session_ids = self.session_cache.get_all_session_ids()

            for session_id in session_ids:
                metadata = self.session_cache.get_session_metadata(session_id)
                if metadata and strategy.should_invalidate(str(session_id), metadata):
                    if self.session_cache.delete(session_id):
                        count += 1

            results["sessions"] = count
            logger.info(f"Invalidated {count} sessions using strategy")

        # Apply to embedding cache
        if cache_type in ("embeddings", "all"):
            count = 0
            hashes = self.embedding_cache.get_all_embedding_hashes()

            for content_hash in hashes:
                data = self.embedding_cache.get_by_hash(content_hash)
                if data and strategy.should_invalidate(content_hash, data):
                    if self.embedding_cache.delete_by_hash(content_hash):
                        count += 1

            results["embeddings"] = count
            logger.info(f"Invalidated {count} embeddings using strategy")

        return results

    def schedule_periodic_invalidation(
        self,
        interval_seconds: int,
        max_age_seconds: int,
    ) -> None:
        """Schedule periodic cache invalidation based on age.

        Args:
            interval_seconds: Interval between invalidation runs
            max_age_seconds: Maximum age before invalidation

        Note:
            This is a placeholder for future implementation with a task scheduler.
            In production, use a task queue (Celery, APScheduler, etc.)
        """
        logger.info(
            f"Periodic invalidation configured: "
            f"interval={interval_seconds}s, max_age={max_age_seconds}s"
        )

        # TODO: Implement with task scheduler
        # For now, just log the configuration
        TimeBasedInvalidation(max_age_seconds)
        logger.info(
            "Periodic invalidation requires task scheduler integration (not yet implemented)"
        )


# Singleton instance
_cache_manager: CacheManager | None = None


def get_cache_manager(redis_cache: RedisCache | None = None) -> CacheManager:
    """Get the singleton cache manager instance.

    Args:
        redis_cache: Optional Redis cache client

    Returns:
        CacheManager instance
    """
    global _cache_manager
    if _cache_manager is None:
        if redis_cache is None:
            raise ValueError("redis_cache required for first initialization")
        _cache_manager = CacheManager(redis_cache)
        logger.info("Initialized cache manager")
    return _cache_manager
