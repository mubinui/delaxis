"""Context management for API requests."""

from contextvars import ContextVar

from src.api.auth import CurrentUser

# Context variable to store the current user for the duration of a request
_current_user_context: ContextVar[CurrentUser | None] = ContextVar(
    "current_user_context", default=None
)


def set_request_user(user: CurrentUser) -> None:
    """Set the current user in the request context."""
    _current_user_context.set(user)


def get_request_user() -> CurrentUser | None:
    """Get the current user from the request context."""
    return _current_user_context.get()
