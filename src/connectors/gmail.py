"""Gmail: search, read, send, reply in thread, and list what arrived since a time.

Connections are made by Google sign-in (OAuth), not a pasted token; the
connection's account label is the mailbox address the actions use.
"""

from __future__ import annotations

import json
from typing import Any

from src.connectors.base import (
    Action,
    AuthSpec,
    Connector,
    ConnectorContext,
    ConnectorError,
    Param,
)
from src.tools import gmail_tool


def _mailbox(ctx: ConnectorContext) -> str:
    if not ctx.secrets.account_label:
        raise ConnectorError("This Gmail connection has no mailbox address; reconnect it.")
    return ctx.secrets.account_label


def _parsed(text: str) -> Any:
    try:
        result = json.loads(text)
    except ValueError:
        return text
    if isinstance(result, dict) and result.get("error"):
        raise ConnectorError(str(result["error"]))
    return result


def search_emails(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    return _parsed(
        gmail_tool.search_emails(
            _mailbox(ctx), query=args["query"], max_results=args.get("max_results", 10)
        )
    )


def read_email(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    return _parsed(gmail_tool.read_email(_mailbox(ctx), message_id=args["message_id"]))


def list_new_messages(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    return _parsed(
        gmail_tool.list_new_messages(
            _mailbox(ctx),
            since_epoch=args["since_epoch"],
            query=args.get("query", ""),
            max_results=args.get("max_results", 20),
        )
    )


def send_email(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    return _parsed(
        gmail_tool.send_email(
            _mailbox(ctx),
            to=args["to"],
            subject=args["subject"],
            body=args["body"],
            cc=args.get("cc", ""),
            bcc=args.get("bcc", ""),
        )
    )


def reply_to_thread(ctx: ConnectorContext, args: dict[str, Any]) -> Any:
    return _parsed(
        gmail_tool.reply_to_thread(
            _mailbox(ctx),
            message_id=args["message_id"],
            body=args["body"],
            cc=args.get("cc", ""),
        )
    )


CONNECTOR = Connector(
    id="gmail",
    name="Gmail",
    icon="gmail",
    description="Search, read, send and reply to email from a connected Google account",
    auth=AuthSpec(kind="oauth", oauth_start="/api/v1/integrations/gmail/auth-url"),
    actions=(
        Action(
            "search_emails",
            "Search mail",
            "read",
            "Search the mailbox with Gmail query syntax, e.g. 'from:alice is:unread newer_than:7d'.",
            (
                Param("query", "string", "Gmail search query"),
                Param(
                    "max_results", "integer", "Most messages to return", required=False, default=10
                ),
            ),
            search_emails,
        ),
        Action(
            "read_email",
            "Read a message",
            "read",
            "One message in full, by the id a search returned.",
            (Param("message_id", "string", "Gmail message id"),),
            read_email,
        ),
        Action(
            "list_new_messages",
            "List new mail",
            "read",
            "Messages received after a time (seconds since 1970), "
            "optionally filtered by a Gmail query.",
            (
                Param("since_epoch", "integer", "Only mail after this Unix time"),
                Param(
                    "query",
                    "string",
                    "Extra Gmail query, e.g. 'label:support'",
                    required=False,
                    default="",
                ),
                Param(
                    "max_results", "integer", "Most messages to return", required=False, default=20
                ),
            ),
            list_new_messages,
        ),
        Action(
            "send_email",
            "Send mail",
            "write",
            "Send a new email. 'to', 'cc' and 'bcc' take comma-separated addresses.",
            (
                Param("to", "string", "Recipients"),
                Param("subject", "string", "Subject"),
                Param("body", "string", "Plain-text body"),
                Param("cc", "string", "Cc", required=False, default=""),
                Param("bcc", "string", "Bcc", required=False, default=""),
            ),
            send_email,
        ),
        Action(
            "reply_to_thread",
            "Reply in thread",
            "write",
            "Reply to a message in its own thread, to its sender.",
            (
                Param("message_id", "string", "The message to reply to"),
                Param("body", "string", "Plain-text reply"),
                Param("cc", "string", "Cc", required=False, default=""),
            ),
            reply_to_thread,
        ),
    ),
)
