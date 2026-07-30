"""SQL-backed authentication store for Delaxis.

Persists local user accounts and API keys in the platform database
(SQLite by default, PostgreSQL in production). Only key hashes are
stored — the plaintext API key is returned exactly once at creation.
"""

import hashlib
import secrets
from datetime import datetime
from typing import Optional
from uuid import UUID

import structlog

from src.infrastructure.database.connection import get_db_manager
from src.infrastructure.database.schema import ApiKey, User

logger = structlog.get_logger(__name__)

# Prefix minted onto new keys. Only hashes are stored, so keys issued under the
# pre-rename prefix cannot be rewritten — authentication accepts both.
API_KEY_PREFIX = "dlx_"
ACCEPTED_API_KEY_PREFIXES = ("dlx_", "oak_")


def hash_api_key(key: str) -> str:
    """Hash an API key for storage/lookup."""
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a new random API key."""
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


class AuthStore:
    """CRUD operations for users and API keys on the SQL database."""

    def __init__(self) -> None:
        self._db = get_db_manager()

    # ------------------------------------------------------------------ users

    def create_user(
        self,
        username: str,
        password_hash: str,
        role: str = "user",
        email: Optional[str] = None,
    ) -> User:
        with self._db.get_session() as session:
            user = User(
                username=username,
                email=email,
                password_hash=password_hash,
                role=role,
            )
            session.add(user)
            session.flush()
            session.refresh(user)
            session.expunge(user)
            return user

    def get_user_by_username(self, username: str) -> Optional[User]:
        with self._db.get_session() as session:
            user = session.query(User).filter(User.username == username).one_or_none()
            if user:
                session.expunge(user)
            return user

    def get_active_user(self, user_id: UUID) -> Optional[User]:
        with self._db.get_session() as session:
            user = (
                session.query(User)
                .filter(User.id == user_id, User.active.is_(True))
                .one_or_none()
            )
            if user:
                session.expunge(user)
            return user

    def count_users(self) -> int:
        with self._db.get_session() as session:
            return session.query(User).count()

    def record_login(self, user_id: UUID) -> None:
        with self._db.get_session() as session:
            session.query(User).filter(User.id == user_id).update(
                {"last_login_at": datetime.utcnow()}
            )

    # --------------------------------------------------------------- api keys

    def create_api_key(
        self,
        name: str,
        key_hash: str,
        role: str = "user",
        user_id: Optional[UUID] = None,
        expires_at: Optional[datetime] = None,
    ) -> ApiKey:
        with self._db.get_session() as session:
            api_key = ApiKey(
                name=name,
                key_hash=key_hash,
                role=role,
                user_id=user_id,
                expires_at=expires_at,
            )
            session.add(api_key)
            session.flush()
            session.refresh(api_key)
            session.expunge(api_key)
            return api_key

    def get_api_key_by_hash(self, key_hash: str) -> Optional[ApiKey]:
        with self._db.get_session() as session:
            api_key = (
                session.query(ApiKey)
                .filter(ApiKey.key_hash == key_hash, ApiKey.active.is_(True))
                .one_or_none()
            )
            if api_key:
                session.expunge(api_key)
            return api_key

    def get_api_key(self, api_key_id: UUID) -> Optional[ApiKey]:
        with self._db.get_session() as session:
            api_key = session.query(ApiKey).filter(ApiKey.id == api_key_id).one_or_none()
            if api_key:
                session.expunge(api_key)
            return api_key

    def list_api_keys(self, user_id: Optional[UUID] = None) -> list[ApiKey]:
        with self._db.get_session() as session:
            query = session.query(ApiKey).filter(ApiKey.active.is_(True))
            if user_id is not None:
                query = query.filter(ApiKey.user_id == user_id)
            keys = query.order_by(ApiKey.created_at.desc()).all()
            for key in keys:
                session.expunge(key)
            return keys

    def update_api_key_last_used(self, api_key_id: UUID) -> None:
        with self._db.get_session() as session:
            session.query(ApiKey).filter(ApiKey.id == api_key_id).update(
                {"last_used_at": datetime.utcnow()}
            )

    def revoke_api_key(self, api_key_id: UUID) -> bool:
        with self._db.get_session() as session:
            updated = (
                session.query(ApiKey)
                .filter(ApiKey.id == api_key_id, ApiKey.active.is_(True))
                .update({"active": False})
            )
            return updated > 0

    def rotate_api_key(self, api_key_id: UUID, new_key_hash: str) -> Optional[ApiKey]:
        with self._db.get_session() as session:
            api_key = session.query(ApiKey).filter(ApiKey.id == api_key_id).one_or_none()
            if api_key is None:
                return None
            api_key.key_hash = new_key_hash
            api_key.last_used_at = None
            session.flush()
            session.refresh(api_key)
            session.expunge(api_key)
            return api_key


_auth_store: Optional[AuthStore] = None


def get_auth_store() -> AuthStore:
    """Get or create the global auth store."""
    global _auth_store
    if _auth_store is None:
        _auth_store = AuthStore()
    return _auth_store


def reset_auth_store() -> None:
    """Reset the global auth store (useful for tests)."""
    global _auth_store
    _auth_store = None
