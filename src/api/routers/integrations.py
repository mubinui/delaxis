"""External integration endpoints (Google OAuth for Gmail tools).

Flow: GET /gmail/auth-url → user consents in a browser tab → Google redirects to
GET /gmail/callback → tokens are encrypted (Fernet) and upserted into
integration_credentials → gmail-type tools can act as that account.
"""

import os
from datetime import timedelta
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from src.api.auth import create_access_token, verify_token
from src.audit_logging import get_logger
from src.tools.gmail_tool import GMAIL_SCOPES, persist_credentials

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])

_STATE_PURPOSE = "gmail_oauth"


def _redirect_uri() -> str:
    return os.environ.get(
        "GOOGLE_OAUTH_REDIRECT_URI",
        "http://localhost:8000/api/v1/integrations/gmail/callback",
    )


def _client_config() -> dict[str, Any]:
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    missing = [
        name
        for name, value in (
            ("GOOGLE_OAUTH_CLIENT_ID", client_id),
            ("GOOGLE_OAUTH_CLIENT_SECRET", client_secret),
            ("ENCRYPTION_KEY", os.environ.get("ENCRYPTION_KEY")),
        )
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Gmail integration is not configured: set {', '.join(missing)} in the environment.",
        )
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [_redirect_uri()],
        }
    }


def _build_flow(state: str | None = None) -> Any:
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        _client_config(),
        scopes=GMAIL_SCOPES,
        redirect_uri=_redirect_uri(),
        state=state,
    )


@router.get("/gmail/auth-url")
async def gmail_auth_url() -> dict[str, str]:
    """Return the Google consent URL. The studio opens it in a new browser tab."""
    # Stateless CSRF protection: a short-lived JWT survives multi-worker deployments.
    # sub must be UUID-shaped because verify_token parses it with UUID().
    state = create_access_token(
        {"sub": "00000000-0000-0000-0000-000000000000", "purpose": _STATE_PURPOSE},
        expires_delta=timedelta(minutes=10),
    )
    flow = _build_flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",  # guarantees a refresh_token even on reconnect
        include_granted_scopes="true",
        state=state,
    )
    return {"auth_url": auth_url, "state": state}


@router.get("/gmail/callback")
async def gmail_callback(
    request: Request, code: str = "", state: str = "", error: str = ""
) -> HTMLResponse:
    """Browser-facing OAuth redirect target (renders HTML, not JSON)."""

    def _page(title: str, message: str, ok: bool) -> HTMLResponse:
        color = "#059669" if ok else "#dc2626"
        return HTMLResponse(
            f"""<!doctype html><html><head><title>{title}</title></head>
            <body style="font-family: system-ui, sans-serif; display:flex; align-items:center;
                         justify-content:center; height:100vh; margin:0; background:#f8fafc;">
              <div style="text-align:center; max-width:420px; padding:2rem; background:white;
                          border:1px solid #e2e8f0; border-radius:12px;">
                <h2 style="color:{color}; margin:0 0 0.5rem;">{title}</h2>
                <p style="color:#475569; font-size:14px;">{message}</p>
              </div>
            </body></html>""",
            status_code=200 if ok else 400,
        )

    if error:
        return _page("Gmail connection failed", f"Google returned: {error}", ok=False)
    if not code or not state:
        return _page("Gmail connection failed", "Missing authorization code or state.", ok=False)

    # Verify the CSRF state token (signature + expiry checked by verify_token).
    try:
        verify_token(state)
    except Exception:
        return _page(
            "Gmail connection failed",
            "Invalid or expired state token. Start over from the studio.",
            ok=False,
        )

    try:
        flow = _build_flow(state=state)
        flow.fetch_token(code=code)
        creds = flow.credentials

        from googleapiclient.discovery import build

        profile = (
            build("gmail", "v1", credentials=creds, cache_discovery=False)
            .users()
            .getProfile(userId="me")
            .execute()
        )
        account_email = profile.get("emailAddress", "")
        if not account_email:
            return _page(
                "Gmail connection failed",
                "Could not resolve the account's email address.",
                ok=False,
            )

        persist_credentials(account_email, creds)
        logger.info("gmail_account_connected", account_email=account_email)
        return _page(
            "Gmail connected",
            f"Account <b>{account_email}</b> is now connected. You can close this window and return to the studio.",
            ok=True,
        )
    except HTTPException as exc:
        return _page("Gmail connection failed", str(exc.detail), ok=False)
    except Exception as exc:
        logger.error("gmail_oauth_callback_failed", error=str(exc), exc_info=True)
        return _page("Gmail connection failed", f"Token exchange failed: {exc}", ok=False)


@router.get("/gmail/status")
async def gmail_status() -> dict[str, Any]:
    """Connection status for the studio's Gmail tool inspector."""
    configured = bool(
        os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        and os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
        and os.environ.get("ENCRYPTION_KEY")
    )

    accounts: list[dict[str, Any]] = []
    try:
        from src.infrastructure.database.integration_store import get_integration_store

        for row in get_integration_store().list_credentials("gmail"):
            accounts.append(
                {
                    "account_email": row.account_email,
                    "scopes": row.scopes or [],
                    "connected_at": row.created_at.isoformat() if row.created_at else None,
                    "token_expiry": row.token_expiry.isoformat() if row.token_expiry else None,
                }
            )
    except Exception as exc:
        logger.warning("gmail_status_lookup_failed", error=str(exc))

    return {
        "provider": "gmail",
        "configured": configured,
        "connected": bool(accounts),
        "accounts": accounts,
    }


@router.delete("/gmail/{account_email}", status_code=status.HTTP_204_NO_CONTENT)
async def gmail_disconnect(account_email: str) -> None:
    """Disconnect an account: best-effort Google revoke, then delete the stored credential."""
    from src.infrastructure.database.integration_store import get_integration_store
    from src.infrastructure.secrets import get_global_credential_manager

    store = get_integration_store()
    row = store.get_credential("gmail", account_email)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gmail account '{account_email}' is not connected",
        )

    # Best-effort revoke at Google; local deletion proceeds regardless.
    try:
        import json as _json

        token_data = _json.loads(
            get_global_credential_manager().decrypt_credential(row.encrypted_token)
        )
        token = token_data.get("refresh_token") or token_data.get("token")
        if token:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post("https://oauth2.googleapis.com/revoke", params={"token": token})
    except Exception as exc:
        logger.warning("gmail_revoke_failed", account_email=account_email, error=str(exc))

    store.delete_credential("gmail", account_email)
