"""Gmail tools backed by a connected Google OAuth account.

Credentials are connected once via /api/v1/integrations/gmail (browser consent
flow) and stored Fernet-encrypted in the integration_credentials table. At
execution time they are decrypted, refreshed if expired, and re-persisted.

OAuth client id/secret always come from environment variables:
GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from email.message import EmailMessage
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

_BODY_TRUNCATE_CHARS = 20_000


def _oauth_client_config() -> tuple[str, str]:
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        missing = "GOOGLE_OAUTH_CLIENT_ID" if not client_id else "GOOGLE_OAUTH_CLIENT_SECRET"
        raise ValueError(f"Gmail integration is not configured: set {missing} in the environment.")
    return client_id, client_secret


def get_gmail_credentials(account_email: str) -> Any:
    """Load, decrypt, refresh-if-expired, and re-persist Gmail OAuth credentials."""
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.credentials import Credentials

    from src.infrastructure.database.integration_store import get_integration_store
    from src.infrastructure.secrets import get_global_credential_manager

    store = get_integration_store()
    row = store.get_credential("gmail", account_email)
    if row is None:
        raise ValueError(
            f"Gmail account '{account_email}' is not connected. "
            "Connect it via the studio's Gmail tool inspector (Integrations)."
        )

    manager = get_global_credential_manager()
    try:
        token_data = json.loads(manager.decrypt_credential(row.encrypted_token))
    except Exception as exc:
        raise ValueError(
            f"Stored Gmail credentials for '{account_email}' could not be decrypted "
            "(was ENCRYPTION_KEY rotated?). Reconnect the account."
        ) from exc

    client_id, client_secret = _oauth_client_config()
    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=client_id,
        client_secret=client_secret,
        scopes=token_data.get("scopes", GMAIL_SCOPES),
    )
    expiry = token_data.get("expiry")
    if expiry:
        try:
            creds.expiry = datetime.fromisoformat(str(expiry).replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        except ValueError:
            pass

    if creds.expired and creds.refresh_token:
        logger.info("gmail_token_refreshing", account_email=account_email)
        creds.refresh(GoogleRequest())
        persist_credentials(account_email, creds)

    return creds


def persist_credentials(account_email: str, creds: Any, user_id: Any = None) -> None:
    """Encrypt and upsert Google credentials for an account."""
    from src.infrastructure.database.integration_store import get_integration_store
    from src.infrastructure.secrets import get_global_credential_manager

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "scopes": list(creds.scopes or GMAIL_SCOPES),
        "expiry": creds.expiry.isoformat() if getattr(creds, "expiry", None) else None,
    }
    encrypted = get_global_credential_manager().encrypt_credential(json.dumps(token_data))
    get_integration_store().upsert_credential(
        provider="gmail",
        account_email=account_email,
        encrypted_token=encrypted,
        scopes=list(creds.scopes or GMAIL_SCOPES),
        token_expiry=getattr(creds, "expiry", None),
        user_id=user_id,
    )


def _gmail_service(account_email: str) -> Any:
    from googleapiclient.discovery import build

    creds = get_gmail_credentials(account_email)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(headers: list[dict[str, str]], name: str) -> str:
    return next(
        (h.get("value", "") for h in headers if h.get("name", "").lower() == name.lower()), ""
    )


def send_email(
    account_email: str, to: str, subject: str, body: str, cc: str = "", bcc: str = ""
) -> str:
    """Send an email from the connected Gmail account; returns the sent message id."""
    if not to:
        return json.dumps({"error": "Recipient ('to') is required."})

    message = EmailMessage()
    message["To"] = to
    message["From"] = account_email
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc
    message.set_content(body)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service = _gmail_service(account_email)
    result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    logger.info("gmail_message_sent", account_email=account_email, message_id=result.get("id"))
    return json.dumps(
        {"status": "sent", "message_id": result.get("id"), "to": to, "subject": subject}
    )


def search_emails(account_email: str, query: str, max_results: int = 10) -> str:
    """Search the mailbox with Gmail query syntax; returns JSON array of message summaries."""
    service = _gmail_service(account_email)
    listing = (
        service.users()
        .messages()
        .list(userId="me", q=query or None, maxResults=max(1, min(int(max_results), 50)))
        .execute()
    )
    summaries: list[dict[str, Any]] = []
    for ref in listing.get("messages", []) or []:
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=ref["id"],
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            )
            .execute()
        )
        headers = msg.get("payload", {}).get("headers", [])
        summaries.append(
            {
                "id": msg.get("id"),
                "threadId": msg.get("threadId"),
                "date": _header(headers, "Date"),
                "from": _header(headers, "From"),
                "to": _header(headers, "To"),
                "subject": _header(headers, "Subject"),
                "snippet": msg.get("snippet", ""),
            }
        )
    return json.dumps(summaries)


def _extract_plain_text(payload: dict[str, Any]) -> str:
    """Walk a Gmail message payload for the text/plain body (fallback: any text part)."""

    def decode(data: str) -> str:
        return base64.urlsafe_b64decode(data.encode()).decode(errors="replace")

    if payload.get("mimeType", "").startswith("text/") and payload.get("body", {}).get("data"):
        return decode(payload["body"]["data"])

    plain, other = "", ""
    for part in payload.get("parts", []) or []:
        text = _extract_plain_text(part)
        if not text:
            continue
        if part.get("mimeType") == "text/plain" and not plain:
            plain = text
        elif not other:
            other = text
    return plain or other


def read_email(account_email: str, message_id: str) -> str:
    """Read one email in full by Gmail message id; returns JSON with headers and body."""
    if not message_id:
        return json.dumps({"error": "message_id is required (use search results)."})

    service = _gmail_service(account_email)
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    payload = msg.get("payload", {})
    headers = payload.get("headers", [])
    body = _extract_plain_text(payload)
    if len(body) > _BODY_TRUNCATE_CHARS:
        body = body[:_BODY_TRUNCATE_CHARS] + "\n…[truncated]"
    return json.dumps(
        {
            "id": msg.get("id"),
            "threadId": msg.get("threadId"),
            "date": _header(headers, "Date"),
            "from": _header(headers, "From"),
            "to": _header(headers, "To"),
            "cc": _header(headers, "Cc"),
            "subject": _header(headers, "Subject"),
            "body": body,
        }
    )
