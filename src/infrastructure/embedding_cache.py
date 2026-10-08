"""Embedding caching layer using Redis."""

import hashlib
import logging
from typing import Any

from src.infrastructure.cache import RedisCache

logger = logging.getLogger(__name__)


class EmbeddingCache:
    """Cache layer for embedding vectors using Redis."""

    # Default TTL for embedding cache (24 hours)
    DEFAULT_EMBEDDING_TTL = 86400

    def __init__(
        self,
        redis_cache: RedisCache,
        embedding_ttl: int = DEFAULT_EMBEDDING_TTL,
    ):
        """Initialize embedding cache.

        Args:
            redis_cache: Redis cache client
            embedding_ttl: Time to live for embedding cache in seconds
        """
        self.redis_cache = redis_cache
        self.embedding_ttl = embedding_ttl
        logger.info(f"Embedding cache initialized (ttl={embedding_ttl}s)")

    def _compute_content_hash(self, content: str, model: str = "default") -> str:
        """Compute hash for content and model combination.

        Args:
            content: Text content to hash
            model: Embedding model name

        Returns:
            SHA256 hash string
        """
        # Combine content and model for unique hash
        combined = f"{model}:{content}"
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    def _embedding_key(self, content_hash: str) -> str:
        """Generate Redis key for embedding.

        Args:
            content_hash: Content hash

        Returns:
            Redis key string
        """
        return f"embedding:{content_hash}"

    def get(
        self,
        content: str,
        model: str = "default",
    ) -> list[float] | None:
        """Get embedding from cache.

        Args:
            content: Text content
            model: Embedding model name

        Returns:
            Cached embedding vector or None if not found
        """
        content_hash = self._compute_content_hash(content, model)
        key = self._embedding_key(content_hash)

        try:
            data = self.redis_cache.get_json(key)
            if data and isinstance(data, dict):
                embedding = data.get("embedding")
                if embedding:
                    logger.debug(
                        f"Embedding cache hit: {content_hash[:16]}... "
                        f"(model={model}, length={len(content)})"
                    )
                    return [float(value) for value in embedding]

            logger.debug(
                f"Embedding cache miss: {content_hash[:16]}... "
                f"(model={model}, length={len(content)})"
            )
            return None
        except Exception as e:
            logger.error(f"Failed to get embedding from cache: {e}", exc_info=True)
            return None

    def set(
        self,
        content: str,
        embedding: list[float],
        model: str = "default",
        ttl: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Set embedding in cache.

        Args:
            content: Text content
            embedding: Embedding vector
            model: Embedding model name
            ttl: Time to live in seconds (uses default if not specified)
            metadata: Optional metadata to store with embedding

        Returns:
            True if successful, False otherwise
        """
        content_hash = self._compute_content_hash(content, model)
        key = self._embedding_key(content_hash)
        ttl = ttl or self.embedding_ttl

        try:
            # Store embedding with metadata
            data = {
                "embedding": embedding,
                "model": model,
                "content_length": len(content),
                "content_hash": content_hash,
            }

            if metadata:
                data["metadata"] = metadata

            result = self.redis_cache.set_json(key, data, ttl)
            if result:
                logger.debug(
                    f"Embedding cached: {content_hash[:16]}... "
                    f"(model={model}, dim={len(embedding)}, ttl={ttl}s)"
                )
            return result
        except Exception as e:
            logger.error(f"Failed to set embedding in cache: {e}", exc_info=True)
            return False

    def get_by_hash(self, content_hash: str) -> dict[str, Any] | None:
        """Get embedding by content hash.

        Args:
            content_hash: Content hash

        Returns:
            Cached embedding data or None if not found
        """
        key = self._embedding_key(content_hash)

        try:
            data = self.redis_cache.get_json(key)
            if data:
                logger.debug(f"Embedding cache hit by hash: {content_hash[:16]}...")
                return dict(data)
            return None
        except Exception as e:
            logger.error(f"Failed to get embedding by hash: {e}", exc_info=True)
            return None

    def delete(self, content: str, model: str = "default") -> bool:
        """Delete embedding from cache.

        Args:
            content: Text content
            model: Embedding model name

        Returns:
            True if deleted, False otherwise
        """
        content_hash = self._compute_content_hash(content, model)
        key = self._embedding_key(content_hash)

        try:
            result = self.redis_cache.delete(key)
            if result:
                logger.debug(f"Embedding deleted from cache: {content_hash[:16]}...")
            return result
        except Exception as e:
            logger.error(f"Failed to delete embedding from cache: {e}", exc_info=True)
            return False

    def delete_by_hash(self, content_hash: str) -> bool:
        """Delete embedding by content hash.

        Args:
            content_hash: Content hash

        Returns:
            True if deleted, False otherwise
        """
        key = self._embedding_key(content_hash)

        try:
            result = self.redis_cache.delete(key)
            if result:
                logger.debug(f"Embedding deleted by hash: {content_hash[:16]}...")
            return result
        except Exception as e:
            logger.error(f"Failed to delete embedding by hash: {e}", exc_info=True)
            return False

    def exists(self, content: str, model: str = "default") -> bool:
        """Check if embedding exists in cache.

        Args:
            content: Text content
            model: Embedding model name

        Returns:
            True if exists, False otherwise
        """
        content_hash = self._compute_content_hash(content, model)
        key = self._embedding_key(content_hash)
        return self.redis_cache.exists(key)

    def get_batch(
        self,
        contents: list[str],
        model: str = "default",
    ) -> dict[str, list[float] | None]:
        """Get multiple embeddings from cache.

        Args:
            contents: List of text contents
            model: Embedding model name

        Returns:
            Dictionary mapping content to embedding (or None if not cached)
        """
        results = {}
        for content in contents:
            results[content] = self.get(content, model)
        return results

    def set_batch(
        self,
        embeddings: dict[str, list[float]],
        model: str = "default",
        ttl: int | None = None,
    ) -> dict[str, bool]:
        """Set multiple embeddings in cache.

        Args:
            embeddings: Dictionary mapping content to embedding vector
            model: Embedding model name
            ttl: Time to live in seconds (uses default if not specified)

        Returns:
            Dictionary mapping content to success status
        """
        results = {}
        for content, embedding in embeddings.items():
            results[content] = self.set(content, embedding, model, ttl)
        return results

    def get_all_embedding_hashes(self) -> list[str]:
        """Get all embedding content hashes from cache.

        Returns:
            List of content hashes
        """
        try:
            keys = self.redis_cache.keys("embedding:*")
            hashes = []
            for key in keys:
                # Extract hash from key (format: "embedding:<hash>")
                content_hash = key.split(":", 1)[1]
                hashes.append(content_hash)
            return hashes
        except Exception as e:
            logger.error(f"Failed to get embedding hashes: {e}", exc_info=True)
            return []

    def clear_all_embeddings(self) -> int:
        """Clear all embeddings from cache.

        Returns:
            Number of embeddings cleared
        """
        try:
            keys = self.redis_cache.keys("embedding:*")
            count = 0
            for key in keys:
                if self.redis_cache.delete(key):
                    count += 1
            logger.info(f"Cleared {count} embeddings from cache")
            return count
        except Exception as e:
            logger.error(f"Failed to clear embeddings: {e}", exc_info=True)
            return 0

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        try:
            keys = self.redis_cache.keys("embedding:*")
            total_embeddings = len(keys)

            # Sample a few embeddings to get average dimension
            sample_size = min(10, total_embeddings)
            dimensions = []

            for key in keys[:sample_size]:
                data = self.redis_cache.get_json(key)
                if data and "embedding" in data:
                    dimensions.append(len(data["embedding"]))

            avg_dimension = sum(dimensions) / len(dimensions) if dimensions else 0

            return {
                "total_embeddings": total_embeddings,
                "average_dimension": avg_dimension,
                "ttl_seconds": self.embedding_ttl,
            }
        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}", exc_info=True)
            return {
                "total_embeddings": 0,
                "average_dimension": 0,
                "ttl_seconds": self.embedding_ttl,
            }
