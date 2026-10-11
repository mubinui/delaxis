"""Jira actions against a mocked API, for Cloud (v3, ADF) and Data Center (v2)."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.connectors.base import ConnectionSecrets, ConnectorContext, ConnectorError
from src.connectors.jira import CONNECTOR, adf_to_text, to_adf

Handler = Callable[[httpx.Request], httpx.Response]


def ctx(
    handler: Handler,
    *,
    version: str = "3",
    username: str | None = "ops@acme.test",
    options: dict[str, Any] | None = None,
) -> ConnectorContext:
    secrets = ConnectionSecrets(
        base_url="https://acme.atlassian.net",
        username=username,
        token="tok",
        options={"api_version": version},
    )
    return ConnectorContext(secrets, options or {}, transport=httpx.MockTransport(handler))


def run(action_id: str, handler: Handler, args: dict[str, Any], **kw: Any) -> Any:
    return CONNECTOR.action(action_id).run(ctx(handler, **kw), args)


def test_cloud_verify_uses_basic_auth_and_records_v3() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/rest/api/3/myself"
        expected = base64.b64encode(b"ops@acme.test:tok").decode()
        assert req.headers["Authorization"] == f"Basic {expected}"
        return httpx.Response(200, json={"displayName": "Ops Bot", "emailAddress": "ops@acme.test"})

    assert CONNECTOR.verify is not None
    result = CONNECTOR.verify(ctx(handler, version=""))
    assert result.account_label == "Ops Bot (ops@acme.test)"
    assert result.options == {"api_version": "3"}


def test_data_center_verify_falls_back_to_v2_with_a_bearer_token() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["Authorization"] == "Bearer tok"
        if req.url.path == "/rest/api/3/myself":
            return httpx.Response(404, json={"message": "no v3"})
        return httpx.Response(200, json={"displayName": "Ops", "name": "ops"})

    assert CONNECTOR.verify is not None
    result = CONNECTOR.verify(ctx(handler, version="", username=None))
    assert result.options == {"api_version": "2"}


def test_adf_round_trip_keeps_paragraphs_and_lines() -> None:
    text = "First line\nsecond line\n\nNew paragraph"
    assert adf_to_text(to_adf(text)) == text


def test_search_uses_the_jql_endpoint_on_cloud() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/rest/api/3/search/jql"
        assert req.url.params["jql"] == "project = OPS"
        return httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "key": "OPS-1",
                        "fields": {
                            "summary": "Login fails",
                            "status": {"name": "To Do"},
                            "assignee": {"displayName": "Ann"},
                            "priority": {"name": "High"},
                            "labels": ["bug"],
                            "issuetype": {"name": "Bug"},
                            "updated": "2026-10-01",
                        },
                    }
                ]
            },
        )

    assert run("search_issues", handler, {"jql": "project = OPS"}) == [
        {
            "key": "OPS-1",
            "summary": "Login fails",
            "status": "To Do",
            "assignee": "Ann",
            "priority": "High",
            "labels": ["bug"],
            "type": "Bug",
            "updated": "2026-10-01",
            "url": "https://acme.atlassian.net/browse/OPS-1",
        }
    ]


def test_search_uses_the_old_endpoint_on_data_center() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/rest/api/2/search"
        return httpx.Response(200, json={"issues": []})

    assert run("search_issues", handler, {"jql": "x"}, version="2", username=None) == []


def test_create_issue_sends_adf_on_cloud_and_defaults_the_project() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        fields = json.loads(req.content)["fields"]
        assert fields["project"] == {"key": "OPS"}
        assert fields["issuetype"] == {"name": "Bug"}
        assert fields["description"]["type"] == "doc"
        return httpx.Response(201, json={"key": "OPS-9", "id": "10009"})

    result = run(
        "create_issue",
        handler,
        {"summary": "Crash", "description": "Steps", "issue_type": "Bug"},
        options={"project": "OPS"},
    )
    assert result == {
        "key": "OPS-9",
        "id": "10009",
        "url": "https://acme.atlassian.net/browse/OPS-9",
    }


def test_create_issue_sends_plain_text_on_data_center() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert json.loads(req.content)["fields"]["description"] == "Steps"
        return httpx.Response(201, json={"key": "OPS-9", "id": "1"})

    run(
        "create_issue",
        handler,
        {"summary": "Crash", "description": "Steps", "project": "OPS"},
        version="2",
        username=None,
    )


def test_get_issue_flattens_description_and_comments() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "key": "OPS-1",
                "fields": {
                    "summary": "S",
                    "description": to_adf("Body"),
                    "status": {"name": "Open"},
                    "reporter": {"displayName": "Rae"},
                    "comment": {
                        "comments": [
                            {
                                "author": {"displayName": "Ann"},
                                "created": "t",
                                "body": to_adf("Hi"),
                            }
                        ]
                    },
                },
            },
        )

    issue = run("get_issue", handler, {"key": "OPS-1"})
    assert issue["description"] == "Body"
    assert issue["comments"] == [{"author": "Ann", "created": "t", "body": "Hi"}]
    assert issue["reporter"] == "Rae"


def test_transition_matches_by_name_case_insensitively() -> None:
    posted: list[Any] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(
                200,
                json={"transitions": [{"id": "31", "name": "Done", "to": {"name": "Closed"}}]},
            )
        posted.append(json.loads(req.content))
        return httpx.Response(204)

    assert run("transition_issue", handler, {"key": "OPS-1", "transition": "done"}) == {
        "key": "OPS-1",
        "transitioned_to": "Closed",
    }
    assert posted == [{"transition": {"id": "31"}}]


def test_transition_by_unknown_name_lists_the_choices() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "transitions": [
                    {"id": "1", "name": "Start", "to": {"name": "In Progress"}},
                    {"id": "2", "name": "Close", "to": {"name": "Closed"}},
                ]
            },
        )

    with pytest.raises(ConnectorError, match="Start, Close"):
        run("transition_issue", handler, {"key": "OPS-1", "transition": "Done"})


def test_assign_by_email_looks_up_the_account_on_cloud() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/rest/api/3/user/search":
            assert req.url.params["query"] == "dev@acme.test"
            return httpx.Response(200, json=[{"accountId": "acc-1", "displayName": "Dev"}])
        assert req.url.path == "/rest/api/3/issue/OPS-1/assignee"
        assert json.loads(req.content) == {"accountId": "acc-1"}
        return httpx.Response(204)

    assert run("assign_issue", handler, {"key": "OPS-1", "assignee": "dev@acme.test"}) == {
        "key": "OPS-1",
        "assignee": "Dev",
    }


def test_assign_to_an_unknown_email_says_so() -> None:
    with pytest.raises(ConnectorError, match="No Jira user"):
        run(
            "assign_issue",
            lambda req: httpx.Response(200, json=[]),
            {"key": "OPS-1", "assignee": "who@acme.test"},
        )
