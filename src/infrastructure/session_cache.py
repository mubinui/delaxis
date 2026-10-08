"""Session caching layer using Redis."""

import logging
from typing import Any
from uuid import UUID

from src.infrastructure.cache import RedisCache
from src.memory.models import ConversationState

logger = logging.getLogger(__name__)


class SessionCache:
    """Cache layer for conversation sessions using Redis."""

    # Default TTL for session cache (1 hour)
    DEFAULT_SESSION_TTL = 3600

    def __init__(
        self,
        redis_cache: RedisCache,
        session_ttl: int = DEFAULT_SESSION_TTL,
    ):
        """Initialize session cache.

        Args:
            redis_cache: Redis cache client
            session_ttl: Time to live for session cache in seconds
        """
        self.redis_cache = redis_cache
        self.session_ttl = session_ttl
        logger.info(f"Session cache initialized (ttl={session_ttl}s)")

    def _session_key(self, session_id: UUID) -> str:
        """Generate Redis key for session.

        Args:
            session_id: Session identifier

        Returns:
            Redis key string
        """
        return f"session:{session_id}"

    def _serialize_session(self, session: ConversationState) -> dict[str, Any]:
        """Serialize session to JSON-compatible dict.

        Args:
            session: Conversation state to serialize

        Returns:
            JSON-compatible dictionary
        """
        # Convert Pydantic model to dict with JSON-compatible types
        data = session.model_dump(mode="json")

        # Ensure UUIDs are strings
        data["session_id"] = str(data["session_id"])

        # Convert message IDs to strings
        for msg in data.get("messages", []):
            msg["id"] = str(msg["id"])

        # Convert agent note IDs to strings
        for note in data.get("agent_notes", []):
            note["id"] = str(note["id"])

        return data

    def _deserialize_session(self, data: dict[str, Any]) -> ConversationState:
        """Deserialize session from JSON dict.

        Args:
            data: JSON dictionary

        Returns:
            ConversationState object
        """
        # Convert string timestamps back to datetime objects if needed
        # Pydantic will handle this automatically in most cases

        # Reconstruct the ConversationState from the dict
        return ConversationState(**data)

    def get(self, session_id: UUID) -> ConversationState | None:
        """Get session from cache.

        Args:
            session_id: Session identifier

        Returns:
            Cached session or None if not found
        """
        key = self._session_key(session_id)

        try:
            data = self.redis_cache.get_json(key)
            if data:
                session = self._deserialize_session(data)
                logger.debug(f"Session cache hit: {session_id}")
                return session
            else:
                logger.debug(f"Session cache miss: {session_id}")
                return None
        except Exception as e:
            logger.error(f"Failed to get session from cache: {e}", exc_info=True)
            return None

    def set(
        self,
        session: ConversationState,
        ttl: int | None = None,
    ) -> bool:
        """Set session in cache.

        Args:
            session: Conversation state to cache
            ttl: Time to live in seconds (uses default if not specified)

        Returns:
            True if successful, False otherwise
        """
        key = self._session_key(session.session_id)
        ttl = ttl or self.session_ttl

        try:
            data = self._serialize_session(session)
            result = self.redis_cache.set_json(key, data, ttl)
            if result:
                logger.debug(f"Session cached: {session.session_id} (ttl={ttl}s)")
            return result
        except Exception as e:
            logger.error(f"Failed to set session in cache: {e}", exc_info=True)
            return False

    def delete(self, session_id: UUID) -> bool:
        """Delete session from cache.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False otherwise
        """
        key = self._session_key(session_id)

        try:
            result = self.redis_cache.delete(key)
            if result:
                logger.debug(f"Session deleted from cache: {session_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to delete session from cache: {e}", exc_info=True)
            return False

    def exists(self, session_id: UUID) -> bool:
        """Check if session exists in cache.

        Args:
            session_id: Session identifier

        Returns:
            True if exists, False otherwise
        """
        key = self._session_key(session_id)
        return self.redis_cache.exists(key)

    def refresh_ttl(self, session_id: UUID, ttl: int | None = None) -> bool:
        """Refresh TTL for a cached session.

        Args:
            session_id: Session identifier
            ttl: New time to live in seconds (uses default if not specified)

        Returns:
            True if successful, False otherwise
        """
        key = self._session_key(session_id)
        ttl = ttl or self.session_ttl

        try:
            result = self.redis_cache.expire(key, ttl)
            if result:
                logger.debug(f"Session TTL refreshed: {session_id} (ttl={ttl}s)")
            return result
        except Exception as e:
            logger.error(f"Failed to refresh session TTL: {e}", exc_info=True)
            return False

    def get_all_session_ids(self) -> list[UUID]:
        """Get all session IDs from cache.

        Returns:
            List of session UUIDs
        """
        try:
            keys = self.redis_cache.keys("session:*")
            session_ids = []
            for key in keys:
                # Extract UUID from key (format: "session:<uuid>")
                uuid_str = key.split(":", 1)[1]
                try:
                    session_ids.append(UUID(uuid_str))
                except ValueError:
                    logger.warning(f"Invalid session key format: {key}")
            return session_ids
        except Exception as e:
            logger.error(f"Failed to get session IDs: {e}", exc_info=True)
            return []

    def clear_all_sessions(self) -> int:
        """Clear all sessions from cache.

        Returns:
            Number of sessions cleared
        """
        try:
            keys = self.redis_cache.keys("session:*")
            count = 0
            for key in keys:
                if self.redis_cache.delete(key):
                    count += 1
            logger.info(f"Cleared {count} sessions from cache")
            return count
        except Exception as e:
            logger.error(f"Failed to clear sessions: {e}", exc_info=True)
            return 0

    def get_session_metadata(self, session_id: UUID) -> dict[str, Any] | None:
        """Get only session metadata without full session data.

        Args:
            session_id: Session identifier

        Returns:
            Session metadata dict or None if not found
        """
        session = self.get(session_id)
        if session:
            return {
                "session_id": str(session.session_id),
                "active": session.active,
                "turn_count": session.turn_count,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
            }
        return None
