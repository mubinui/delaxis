"""Authentication and authorization module for Delaxis."""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from src.config.settings import get_settings
from src.infrastructure.secrets import get_global_credential_manager

logger = structlog.get_logger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer token scheme - auto_error=False allows optional authentication
security = HTTPBearer(auto_error=False)


from enum import Enum

from src.infrastructure.database.auth_store import (
    ACCEPTED_API_KEY_PREFIXES,
    AuthStore,
    generate_api_key,
    get_auth_store,
    hash_api_key,
)


class UserRole(str, Enum):
    """User roles enum."""
    ADMIN = "admin"
    USER = "user"
    READONLY = "readonly"


class APIKeyCreate(BaseModel):
    """Request payload for creating an API key."""
    name: str = ""
    user_id: Optional[UUID] = None
    role: UserRole = UserRole.USER
    expires_at: Optional[datetime] = None


class APIKeyResponse(BaseModel):
    """API key response — includes the plaintext key exactly once (at creation/rotation)."""
    id: UUID
    name: str
    key: str
    user_id: Optional[UUID] = None
    role: UserRole
    active: bool = True
    created_at: datetime
    expires_at: Optional[datetime] = None


class APIKeyInfo(BaseModel):
    """API key metadata (never includes the key itself)."""
    id: UUID
    name: str
    user_id: Optional[UUID] = None
    role: UserRole
    active: bool = True
    created_at: datetime
    expires_at: Optional[datetime] = None


class UserCreate(BaseModel):
    """Request payload for creating a user."""
    username: str
    password: str
    email: Optional[str] = None
    role: UserRole = UserRole.USER


class UserResponse(BaseModel):
    """Public user representation."""
    id: UUID
    username: str
    role: UserRole
    created_at: datetime


class Token(BaseModel):
    """Model for JWT tokens."""
    access_token: str
    token_type: str
    expires_in: int


class TokenData(BaseModel):
    """Model for token data."""
    user_id: Optional[UUID] = None
    username: Optional[str] = None
    role: Optional[UserRole] = None


class CurrentUser(BaseModel):
    """Model for current authenticated user."""
    user_id: Optional[UUID] = None
    username: Optional[str] = None
    api_key_id: Optional[UUID] = None
    role: UserRole
    roles: Optional[list[str]] = None  # Multiple roles from x-client-ref header
    auth_method: str  # "api_key", "jwt", "keycloak", or "development"
    raw_token: Optional[str] = None  # Raw JWT token for forwarding to external services


# Re-export for backwards compatibility
__all__ = [
    "APIKeyCreate",
    "APIKeyInfo", 
    "APIKeyResponse",
    "CurrentUser",
    "Token",
    "TokenData",
    "UserCreate",
    "UserResponse",
    "UserRole",
    "create_access_token",
    "get_current_user",
    "require_admin",
    "require_readonly",
    "require_user",
    "verify_token",
    "APIKeyManager",
    "UserManager",
]


# Use global credential manager for encryption
credential_manager = get_global_credential_manager()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    settings = get_settings()
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.security.access_token_expire_minutes)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, 
        settings.security.secret_key, 
        algorithm=settings.security.algorithm
    )
    return encoded_jwt


def verify_token(token: str) -> TokenData:
    """Verify and decode a JWT token."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, 
            settings.security.secret_key, 
            algorithms=[settings.security.algorithm]
        )
        user_id: str = payload.get("sub")
        username: str = payload.get("username")
        role: str = payload.get("role")
        
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        token_data = TokenData(
            user_id=UUID(user_id) if user_id else None,
            username=username,
            role=UserRole(role) if role else None
        )
        return token_data
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def authenticate_api_key(
    credentials: HTTPAuthorizationCredentials,
) -> CurrentUser:
    """Authenticate using API key."""
    if not credentials.credentials.startswith(ACCEPTED_API_KEY_PREFIXES):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    store = get_auth_store()

    # Hash the provided key to compare with stored hash
    key_hash = hash_api_key(credentials.credentials)

    # Find matching API key in database
    api_key = store.get_api_key_by_hash(key_hash)
    if not api_key:
        logger.warning("api_key_authentication_failed", key_prefix=credentials.credentials[:10])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if key is expired
    if api_key.expires_at and api_key.expires_at < datetime.utcnow():
        logger.warning("api_key_expired", api_key_id=str(api_key.id))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last used timestamp
    store.update_api_key_last_used(api_key.id)

    logger.info(
        "api_key_authentication_successful",
        api_key_id=str(api_key.id),
        role=api_key.role,
    )

    return CurrentUser(
        api_key_id=api_key.id,
        user_id=api_key.user_id,
        role=UserRole(api_key.role),
        auth_method="api_key",
    )


async def authenticate_jwt(
    credentials: HTTPAuthorizationCredentials,
) -> CurrentUser:
    """Authenticate using JWT token."""
    token_data = verify_token(credentials.credentials)

    if not token_data.user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    store = get_auth_store()
    user = store.get_active_user(token_data.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.info(
        "jwt_authentication_successful",
        user_id=str(user.id),
        username=user.username,
        role=user.role,
    )

    return CurrentUser(
        user_id=user.id,
        username=user.username,
        role=UserRole(user.role),
        auth_method="jwt",
    )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> CurrentUser:
    """Get current authenticated user (supports Keycloak, API key, and JWT)."""
    # First check if user was already authenticated by Keycloak middleware
    from src.api.context import get_request_user
    keycloak_user = get_request_user()
    if keycloak_user is not None:
        logger.debug(
            "using_keycloak_authenticated_user",
            username=keycloak_user.username,
            auth_method=keycloak_user.auth_method,
        )
        return keycloak_user
    
    # In development mode, allow access without authentication
    settings = get_settings()
    if settings.app.environment == "development" and credentials is None:
        logger.warning("Development mode: allowing unauthenticated access")
        return CurrentUser(
            user_id=UUID("00000000-0000-0000-0000-000000000000"),
            username="development",
            role=UserRole.ADMIN,
            auth_method="development"
        )
    
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Try API key authentication first
    if credentials.credentials.startswith(ACCEPTED_API_KEY_PREFIXES):
        return await authenticate_api_key(credentials)
    else:
        # Try JWT authentication
        return await authenticate_jwt(credentials)


def require_role(required_role: UserRole):
    """Dependency factory for role-based access control."""
    async def role_checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        # Admin can access everything
        if current_user.role == UserRole.ADMIN:
            return current_user
        
        # Check specific role requirements
        if required_role == UserRole.ADMIN and current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        elif required_role == UserRole.USER and current_user.role == UserRole.READONLY:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User access required"
            )
        
        return current_user
    
    return role_checker


# Convenience dependencies
require_admin = require_role(UserRole.ADMIN)
require_user = require_role(UserRole.USER)
require_readonly = require_role(UserRole.READONLY)


class UserManager:
    """Manages local user accounts backed by the SQL database."""

    def __init__(self, store: Optional[AuthStore] = None):
        self.store = store or get_auth_store()

    def create_user(self, user_data: UserCreate) -> UserResponse:
        """Create a new user with a bcrypt-hashed password."""
        if self.store.get_user_by_username(user_data.username):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username already exists: {user_data.username}",
            )
        user = self.store.create_user(
            username=user_data.username,
            password_hash=pwd_context.hash(user_data.password),
            role=user_data.role.value,
            email=user_data.email,
        )
        logger.info("user_created", user_id=str(user.id), username=user.username)
        return UserResponse(
            id=user.id,
            username=user.username,
            role=UserRole(user.role),
            created_at=user.created_at,
        )

    def authenticate_user(self, username: str, password: str) -> Optional[UserResponse]:
        """Verify username/password; return the user or None."""
        user = self.store.get_user_by_username(username)
        if user is None or not user.active:
            return None
        if not pwd_context.verify(password, user.password_hash):
            return None
        self.store.record_login(user.id)
        return UserResponse(
            id=user.id,
            username=user.username,
            role=UserRole(user.role),
            created_at=user.created_at,
        )


class APIKeyManager:
    """Manages API keys backed by the SQL database."""

    def __init__(self, store: Optional[AuthStore] = None):
        self.store = store or get_auth_store()

    def create_api_key(self, api_key_data: APIKeyCreate) -> APIKeyResponse:
        """Create a new API key; the plaintext key is returned only here."""
        plaintext = generate_api_key()
        api_key = self.store.create_api_key(
            name=api_key_data.name or "api-key",
            key_hash=hash_api_key(plaintext),
            role=api_key_data.role.value,
            user_id=api_key_data.user_id,
            expires_at=api_key_data.expires_at,
        )
        logger.info("api_key_created", api_key_id=str(api_key.id), name=api_key.name)
        return APIKeyResponse(
            id=api_key.id,
            name=api_key.name,
            key=plaintext,
            user_id=api_key.user_id,
            role=UserRole(api_key.role),
            active=api_key.active,
            created_at=api_key.created_at,
            expires_at=api_key.expires_at,
        )

    def list_api_keys(self, user_id: Optional[str] = None) -> list[APIKeyInfo]:
        """List active API keys, optionally filtered by owner."""
        parsed_user_id = UUID(user_id) if user_id else None
        return [
            APIKeyInfo(
                id=key.id,
                name=key.name,
                user_id=key.user_id,
                role=UserRole(key.role),
                active=key.active,
                created_at=key.created_at,
                expires_at=key.expires_at,
            )
            for key in self.store.list_api_keys(parsed_user_id)
        ]

    def revoke_api_key(self, api_key_id: UUID) -> bool:
        """Deactivate an API key."""
        revoked = self.store.revoke_api_key(api_key_id)
        if revoked:
            logger.info("api_key_revoked", api_key_id=str(api_key_id))
        return revoked

    def rotate_api_key(self, api_key_id: UUID) -> Optional[APIKeyResponse]:
        """Replace an API key's secret; the new plaintext key is returned only here."""
        plaintext = generate_api_key()
        api_key = self.store.rotate_api_key(api_key_id, hash_api_key(plaintext))
        if api_key is None:
            return None
        logger.info("api_key_rotated", api_key_id=str(api_key_id))
        return APIKeyResponse(
            id=api_key.id,
            name=api_key.name,
            key=plaintext,
            user_id=api_key.user_id,
            role=UserRole(api_key.role),
            active=api_key.active,
            created_at=api_key.created_at,
            expires_at=api_key.expires_at,
        )


def bootstrap_admin_user() -> None:
    """Create the initial admin user from env vars if no users exist.

    Set DELAXIS_ADMIN_USERNAME and DELAXIS_ADMIN_PASSWORD to enable; skipped otherwise.
    """
    from src.config.env_compat import env

    username = env("DELAXIS_ADMIN_USERNAME")
    password = env("DELAXIS_ADMIN_PASSWORD")
    if not username or not password:
        return
    try:
        store = get_auth_store()
        if store.count_users() > 0:
            return
        UserManager(store).create_user(
            UserCreate(username=username, password=password, role=UserRole.ADMIN)
        )
        logger.info("bootstrap_admin_created", username=username)
    except Exception as exc:
        logger.warning("bootstrap_admin_failed", error=str(exc))
