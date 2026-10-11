"""Gmail as a connector, and the two new mailbox calls behind it."""

from __future__ import annotations

import base64
import json
from email import message_from_bytes
from typing import Any

import pytest

from src.connectors.base import ConnectionSecrets, ConnectorContext
from src.connectors.gmail import CONNECTOR
from src.tools import gmail_tool


class _Call:
    def __init__(self, result: Any, sink: list[Any] | None = None, payload: Any = None) -> None:
        self._result = result
        if sink is not None:
            sink.append(payload)

    def execute(self) -> Any:
        return self._result


class FakeMessages:
    def __init__(self) -> None:
        self.sent: list[Any] = []
        self.listed: list[Any] = []

    def get(
        self,
        userId: str,  # noqa: N803 - the Google client's own argument names
        id: str,  # noqa: A002
        format: str = "full",  # noqa: A002
        metadataHeaders: Any = None,  # noqa: N803
    ) -> _Call:
        return _Call(
            {
                "id": id,
                "threadId": "thr-1",
                "snippet": "My login fails",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "User <user@acme.test>"},
                        {"name": "Subject", "value": "Login fails"},
                        {"name": "Message-ID", "value": "<orig@acme.test>"},
                        {"name": "Date", "value": "Mon, 6 Oct 2026 10:00:00 +0000"},
                    ]
                },
            }
        )

    def send(self, userId: str, body: dict[str, Any]) -> _Call:  # noqa: N803
        return _Call({"id": "sent-1", "threadId": body.get("threadId")}, self.sent, body)

    def list(self, userId: str, q: str, maxResults: int) -> _Call:  # noqa: N803
        return _Call({"messages": [{"id": "m1"}]}, self.listed, q)


class FakeService:
    def __init__(self) -> None:
        self.messages_api = FakeMessages()

    def users(self) -> FakeService:
        return self

    def messages(self) -> FakeMessages:
        return self.messages_api


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> FakeService:
    fake = FakeService()
    monkeypatch.setattr(gmail_tool, "_gmail_service", lambda account_email: fake)
    return fake


def test_reply_stays_in_the_thread_and_quotes_the_subject(service: FakeService) -> None:
    result = json.loads(gmail_tool.reply_to_thread("ops@acme.test", "m1", "Fixed now."))
    assert result["status"] == "sent" and result["thread_id"] == "thr-1"
    sent = service.messages_api.sent[0]
    assert sent["threadId"] == "thr-1"
    mail = message_from_bytes(base64.urlsafe_b64decode(sent["raw"]))
    assert mail["To"] == "User <user@acme.test>"
    assert mail["Subject"] == "Re: Login fails"
    assert mail["In-Reply-To"] == "<orig@acme.test>"
    assert "<orig@acme.test>" in mail["References"]


def test_list_new_messages_queries_after_the_cursor(service: FakeService) -> None:
    result = json.loads(
        gmail_tool.list_new_messages("ops@acme.test", since_epoch=1760000000, query="label:support")
    )
    assert service.messages_api.listed == ["after:1760000000 label:support"]
    assert result[0]["subject"] == "Login fails"


def test_gmail_connector_uses_the_connection_mailbox(service: FakeService) -> None:
    secrets = ConnectionSecrets(
        base_url=None, username=None, token="", account_label="ops@acme.test"
    )
    ctx = ConnectorContext(secrets, {})
    out = CONNECTOR.action("reply_to_thread").run(ctx, {"message_id": "m1", "body": "Done"})
    assert out["status"] == "sent"


def test_gmail_connector_is_oauth_with_a_start_path() -> None:
    assert CONNECTOR.auth.kind == "oauth"
    assert CONNECTOR.auth.oauth_start == "/api/v1/integrations/gmail/auth-url"
    assert {a.id: a.kind for a in CONNECTOR.actions} == {
        "search_emails": "read",
        "read_email": "read",
        "list_new_messages": "read",
        "send_email": "write",
        "reply_to_thread": "write",
    }
