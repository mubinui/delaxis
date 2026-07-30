"""Single-use tickets that authorise one voice WebSocket connection.

FastAPI's HTTP middleware — JWT validation and rate limiting both — does not run
on WebSocket connections. A voice socket that authenticated itself inline would
therefore be the one unthrottled, unlogged entry point in the application, and
the one that bills continuously while open.

So the socket carries no credentials of its own. The client first calls the
ordinary (authenticated, logged, rate-limited) ticket endpoint, and redeems the
short-lived ticket it gets back when connecting. All the policy lives on the
HTTP side where the middleware already works.

Tickets are signed JWTs rather than server-side state so they survive more than
one worker process, and are single-use via a small TTL cache of spent ids.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from cachetools import TTLCache
from jose import JWTError, jwt

from src.config.settings import get_settings

TICKET_TYPE = "voice"

# What a ticket is for. "session" speaks into an existing conversation and its
# transcript is persisted there; "builder" is a design conversation in the Studio
# that belongs to no workflow, so it has no session to attach to.
PURPOSE_SESSION = "session"
PURPOSE_BUILDER = "builder"
PURPOSES = (PURPOSE_SESSION, PURPOSE_BUILDER)

# Spent ticket ids. Sized well above any realistic burst; entries expire on
# their own so this never needs sweeping. Per-process, which is sufficient: a
# ticket replayed against a different worker still cannot outlive its TTL.
_spent: TTLCache[str, bool] = TTLCache(maxsize=4096, ttl=300)


class TicketError(ValueError):
    """Raised when a ticket is missing, malformed, expired, or already used."""


def mint(
    *,
    session_id: str,
    deployment: str | None,
    purpose: str = PURPOSE_SESSION,
) -> tuple[str, int]:
    """Issue a ticket for one voice session. Returns ``(ticket, ttl_seconds)``."""
    settings = get_settings()
    ttl = max(5, int(settings.voice.ticket_ttl_seconds))

    from src.api.auth import create_access_token

    token = create_access_token(
        {
            "typ": TICKET_TYPE,
            "pur": purpose if purpose in PURPOSES else PURPOSE_SESSION,
            "sid": session_id,
            "dep": deployment or "",
            "jti": secrets.token_urlsafe(16),
        },
        expires_delta=timedelta(seconds=ttl),
    )
    return token, ttl


def redeem(ticket: str) -> tuple[str, str | None, str]:
    """Verify and consume a ticket.

    Returns ``(session_id, deployment_id, purpose)``. Raises TicketError for
    anything that is not a live, unused voice ticket.
    """
    if not ticket:
        raise TicketError("missing ticket")

    settings = get_settings()
    try:
        payload = jwt.decode(
            ticket,
            settings.security.secret_key,
            algorithms=[settings.security.algorithm],
        )
    except JWTError as exc:
        raise TicketError("invalid or expired ticket") from exc

    # A ticket must not be interchangeable with a normal access token — those
    # are long-lived and much easier to come by.
    if payload.get("typ") != TICKET_TYPE:
        raise TicketError("not a voice ticket")

    jti = str(payload.get("jti") or "")
    if not jti:
        raise TicketError("ticket has no id")
    if jti in _spent:
        raise TicketError("ticket already used")
    _spent[jti] = True

    purpose = str(payload.get("pur") or PURPOSE_SESSION)
    if purpose not in PURPOSES:
        raise TicketError("unknown ticket purpose")

    session_id = str(payload.get("sid") or "")
    # A builder ticket is a design conversation with no workflow behind it, so it
    # legitimately carries no session.
    if not session_id and purpose == PURPOSE_SESSION:
        raise TicketError("ticket has no session")

    return session_id, (str(payload.get("dep")) or None), purpose


def reset() -> None:
    """Forget spent tickets (tests only)."""
    _spent.clear()
