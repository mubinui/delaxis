"""LLM caching integration with CrewAI."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.infrastructure.cache import RedisCache
from src.utils.time import parse_utc

logger = logging.getLogger(__name__)


@dataclass
class CacheMetrics:
    """Metrics for LLM cache performance."""

    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_tokens_saved: int = 0
    total_cost_saved: float = 0.0
    last_reset: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate as percentage."""
        if self.total_requests == 0:
            return 0.0
        return (self.cache_hits / self.total_requests) * 100

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "total_requests": self.total_requests,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_rate": round(self.hit_rate, 2),
            "total_tokens_saved": self.total_tokens_saved,
            "total_cost_saved": round(self.total_cost_saved, 4),
            "last_reset": self.last_reset.isoformat(),
        }


class LLMCacheMonitor:
    """
    Monitor for LLM cache performance.

    Uses Redis or in-memory caching for LLM responses. When caching is enabled,
    responses are cached based on the request parameters. This monitor
    tracks cache performance metrics.
    """

    def __init__(
        self,
        redis_cache: RedisCache | None = None,
        enable_metrics: bool = True,
    ):
        """Initialize LLM cache monitor.

        Args:
            redis_cache: Optional Redis cache for persisting metrics
            enable_metrics: Whether to track metrics
        """
        self.redis_cache = redis_cache
        self.enable_metrics = enable_metrics
        self.metrics = CacheMetrics()

        logger.info(f"LLM cache monitor initialized (metrics_enabled={enable_metrics})")

    def record_request(
        self,
        cache_hit: bool,
        tokens_saved: int = 0,
        cost_saved: float = 0.0,
    ) -> None:
        """Record an LLM request and its cache status.

        Args:
            cache_hit: Whether the request was served from cache
            tokens_saved: Number of tokens saved by cache hit
            cost_saved: Cost saved by cache hit (in USD)
        """
        if not self.enable_metrics:
            return

        self.metrics.total_requests += 1

        if cache_hit:
            self.metrics.cache_hits += 1
            self.metrics.total_tokens_saved += tokens_saved
            self.metrics.total_cost_saved += cost_saved
            logger.debug(
                f"LLM cache hit (tokens_saved={tokens_saved}, cost_saved=${cost_saved:.4f})"
            )
        else:
            self.metrics.cache_misses += 1
            logger.debug("LLM cache miss")

        # Persist metrics to Redis if available
        if self.redis_cache:
            self._persist_metrics()

    def get_metrics(self) -> CacheMetrics:
        """Get current cache metrics.

        Returns:
            Current cache metrics
        """
        # Load from Redis if available
        if self.redis_cache:
            self._load_metrics()

        return self.metrics

    def reset_metrics(self) -> None:
        """Reset cache metrics."""
        logger.info("Resetting LLM cache metrics")
        self.metrics = CacheMetrics()

        # Clear from Redis if available
        if self.redis_cache:
            self.redis_cache.delete("llm_cache:metrics")

    def _persist_metrics(self) -> None:
        """Persist metrics to Redis."""
        if not self.redis_cache:
            return

        try:
            self.redis_cache.set_json(
                "llm_cache:metrics",
                self.metrics.to_dict(),
                ttl=None,  # No expiration for metrics
            )
        except Exception as e:
            logger.error(f"Failed to persist LLM cache metrics: {e}")

    def _load_metrics(self) -> None:
        """Load metrics from Redis."""
        if not self.redis_cache:
            return

        try:
            data = self.redis_cache.get_json("llm_cache:metrics")
            if data:
                self.metrics.total_requests = data.get("total_requests", 0)
                self.metrics.cache_hits = data.get("cache_hits", 0)
                self.metrics.cache_misses = data.get("cache_misses", 0)
                self.metrics.total_tokens_saved = data.get("total_tokens_saved", 0)
                self.metrics.total_cost_saved = data.get("total_cost_saved", 0.0)

                # Parse last_reset timestamp
                last_reset_str = data.get("last_reset")
                if last_reset_str:
                    self.metrics.last_reset = parse_utc(last_reset_str)
        except Exception as e:
            logger.error(f"Failed to load LLM cache metrics: {e}")


class CrewAICacheConfig:
    """
    Helper class for configuring CrewAI's built-in caching.

    Supports caching through Redis or in-memory backends.
    This class provides helpers for LLM caching configuration.
    """

    @staticmethod
    def get_default_cache_seed() -> int:
        """Get default cache seed.

        Returns:
            Default cache seed (42)
        """
        return 42

    @staticmethod
    def create_llm_config_with_cache(
        config_list: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: int = 120,
        cache_seed: int | None = 42,
    ) -> dict[str, Any]:
        """Create llm_config with caching enabled.

        Args:
            config_list: List of LLM configurations
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate
            timeout: Request timeout in seconds
            cache_seed: Cache seed for CrewAI (None to disable caching)

        Returns:
            llm_config dictionary with caching enabled
        """
        llm_config: dict[str, Any] = {
            "config_list": config_list,
            "temperature": temperature,
            "timeout": timeout,
        }

        if max_tokens is not None:
            llm_config["max_tokens"] = max_tokens

        if cache_seed is not None:
            llm_config["cache_seed"] = cache_seed
            logger.debug(f"LLM config created with cache_seed={cache_seed}")
        else:
            logger.debug("LLM config created without caching")

        return llm_config

    @staticmethod
    def enable_cache_in_config(
        llm_config: dict[str, Any],
        cache_seed: int = 42,
    ) -> dict[str, Any]:
        """Enable caching in existing llm_config.

        Args:
            llm_config: Existing llm_config dictionary
            cache_seed: Cache seed for CrewAI

        Returns:
            Updated llm_config with caching enabled
        """
        llm_config["cache_seed"] = cache_seed
        logger.debug(f"Enabled caching in llm_config with cache_seed={cache_seed}")
        return llm_config

    @staticmethod
    def disable_cache_in_config(llm_config: dict[str, Any]) -> dict[str, Any]:
        """Disable caching in existing llm_config.

        Args:
            llm_config: Existing llm_config dictionary

        Returns:
            Updated llm_config with caching disabled
        """
        if "cache_seed" in llm_config:
            del llm_config["cache_seed"]
            logger.debug("Disabled caching in llm_config")
        return llm_config

    @staticmethod
    def is_cache_enabled(llm_config: dict[str, Any]) -> bool:
        """Check if caching is enabled in llm_config.

        Args:
            llm_config: llm_config dictionary

        Returns:
            True if caching is enabled, False otherwise
        """
        return "cache_seed" in llm_config and llm_config["cache_seed"] is not None


# Singleton instance
_llm_cache_monitor: LLMCacheMonitor | None = None


def get_llm_cache_monitor(
    redis_cache: RedisCache | None = None,
) -> LLMCacheMonitor:
    """Get the singleton LLM cache monitor instance.

    Args:
        redis_cache: Optional Redis cache for persisting metrics

    Returns:
        LLMCacheMonitor instance
    """
    global _llm_cache_monitor
    if _llm_cache_monitor is None:
        _llm_cache_monitor = LLMCacheMonitor(redis_cache=redis_cache)
        logger.info("Initialized LLM cache monitor")
    return _llm_cache_monitor
