"""Redis caching infrastructure for Delaxis."""

import json
import logging
from typing import Any, Optional
from datetime import timedelta

import redis
from redis.connection import ConnectionPool
from redis.exceptions import ConnectionError, TimeoutError, RedisError

logger = logging.getLogger(__name__)


class RedisCache:
    """Redis cache client with connection pooling and reconnection logic."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        max_connections: int = 50,
        socket_timeout: int = 5,
        socket_connect_timeout: int = 5,
        retry_on_timeout: bool = True,
        decode_responses: bool = True,
    ):
        """Initialize Redis cache with connection pool.

        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
            password: Redis password (optional)
            max_connections: Maximum connections in pool
            socket_timeout: Socket timeout in seconds
            socket_connect_timeout: Socket connect timeout in seconds
            retry_on_timeout: Whether to retry on timeout
            decode_responses: Whether to decode responses to strings
        """
        self.host = host
        self.port = port
        self.db = db
        self.password = password

        # Create connection pool
        self.pool = ConnectionPool(
            host=host,
            port=port,
            db=db,
            password=password,
            max_connections=max_connections,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            retry_on_timeout=retry_on_timeout,
            decode_responses=decode_responses,
        )

        # Create Redis client
        self.client = redis.Redis(connection_pool=self.pool)

        logger.info(
            f"Redis cache initialized: {host}:{port}/{db} "
            f"(max_connections={max_connections})"
        )

    def ping(self) -> bool:
        """Check if Redis connection is alive.

        Returns:
            True if connection is alive, False otherwise
        """
        try:
            return self.client.ping()
        except (ConnectionError, TimeoutError, RedisError) as e:
            logger.error(f"Redis ping failed: {e}")
            return False

    def get(self, key: str) -> Optional[str]:
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found
        """
        try:
            value = self.client.get(key)
            if value:
                logger.debug(f"Cache hit: {key}")
            else:
                logger.debug(f"Cache miss: {key}")
            return value
        except (ConnectionError, TimeoutError, RedisError) as e:
            logger.error(f"Redis get failed for key '{key}': {e}")
            return None

    def set(
        self,
        key: str,
        value: str,
        ttl: Optional[int] = None,
    ) -> bool:
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (optional)

        Returns:
            True if successful, False otherwise
        """
        try:
            if ttl:
                result = self.client.setex(key, ttl, value)
            else:
                result = self.client.set(key, value)
            logger.debug(f"Cache set: {key} (ttl={ttl})")
            return bool(result)
        except (ConnectionError, TimeoutError, RedisError) as e:
            logger.error(f"Redis set failed for key '{key}': {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete value from cache.

        Args:
            key: Cache key

        Returns:
            True if key was deleted, False otherwise
        """
        try:
            result = self.client.delete(key)
            logger.debug(f"Cache delete: {key}")
            return bool(result)
        except (ConnectionError, TimeoutError, RedisError) as e:
            logger.error(f"Redis delete failed for key '{key}': {e}")
            return False

    def exists(self, key: str) -> bool:
        """Check if key exists in cache.

        Args:
            key: Cache key

        Returns:
            True if key exists, False otherwise
        """
        try:
            return bool(self.client.exists(key))
        except (ConnectionError, TimeoutError, RedisError) as e:
            logger.error(f"Redis exists check failed for key '{key}': {e}")
            return False

    def expire(self, key: str, ttl: int) -> bool:
        """Set expiration time for key.

        Args:
            key: Cache key
            ttl: Time to live in seconds

        Returns:
            True if successful, False otherwise
        """
        try:
            result = self.client.expire(key, ttl)
            logger.debug(f"Cache expire: {key} (ttl={ttl})")
            return bool(result)
        except (ConnectionError, TimeoutError, RedisError) as e:
            logger.error(f"Redis expire failed for key '{key}': {e}")
            return False

    def get_json(self, key: str) -> Optional[Any]:
        """Get JSON value from cache.

        Args:
            key: Cache key

        Returns:
            Deserialized JSON value or None if not found
        """
        value = self.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON for key '{key}': {e}")
                return None
        return None

    def set_json(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> bool:
        """Set JSON value in cache.

        Args:
            key: Cache key
            value: Value to serialize and cache
            ttl: Time to live in seconds (optional)

        Returns:
            True if successful, False otherwise
        """
        try:
            json_value = json.dumps(value)
            return self.set(key, json_value, ttl)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize JSON for key '{key}': {e}")
            return False

    def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """Increment counter in cache.

        Args:
            key: Cache key
            amount: Amount to increment by

        Returns:
            New value after increment or None on error
        """
        try:
            result = self.client.incrby(key, amount)
            logger.debug(f"Cache increment: {key} by {amount}")
            return result
        except (ConnectionError, TimeoutError, RedisError) as e:
            logger.error(f"Redis increment failed for key '{key}': {e}")
            return None

    def decrement(self, key: str, amount: int = 1) -> Optional[int]:
        """Decrement counter in cache.

        Args:
            key: Cache key
            amount: Amount to decrement by

        Returns:
            New value after decrement or None on error
        """
        try:
            result = self.client.decrby(key, amount)
            logger.debug(f"Cache decrement: {key} by {amount}")
            return result
        except (ConnectionError, TimeoutError, RedisError) as e:
            logger.error(f"Redis decrement failed for key '{key}': {e}")
            return None

    def keys(self, pattern: str = "*") -> list[str]:
        """Get keys matching pattern.

        Args:
            pattern: Key pattern (supports wildcards)

        Returns:
            List of matching keys
        """
        try:
            return [key.decode() if isinstance(key, bytes) else key 
                    for key in self.client.keys(pattern)]
        except (ConnectionError, TimeoutError, RedisError) as e:
            logger.error(f"Redis keys failed for pattern '{pattern}': {e}")
            return []

    def flush_db(self) -> bool:
        """Flush all keys in current database.

        Returns:
            True if successful, False otherwise
        """
        try:
            result = self.client.flushdb()
            logger.warning(f"Flushed Redis database {self.db}")
            return bool(result)
        except (ConnectionError, TimeoutError, RedisError) as e:
            logger.error(f"Redis flush failed: {e}")
            return False

    def close(self) -> None:
        """Close Redis connection pool."""
        try:
            self.pool.disconnect()
            logger.info("Redis connection pool closed")
        except Exception as e:
            logger.error(f"Error closing Redis connection pool: {e}")

    def __enter__(self) -> "RedisCache":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()
