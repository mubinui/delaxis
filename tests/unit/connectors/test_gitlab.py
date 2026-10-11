"""GitLab actions against a mocked API: the right calls, the right shapes."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.connectors.base import ConnectionSecrets, ConnectorContext, ConnectorError
from src.connectors.gitlab import CONNECTOR

Handler = Callable[[httpx.Request], httpx.Response]


def ctx(handler: Handler, options: dict[str, Any] | None = None) -> ConnectorContext:
    secrets = ConnectionSecrets(base_url="https://gitlab.test", username=None, token="glpat-x")
    return ConnectorContext(secrets, options or {}, transport=httpx.MockTransport(handler))


def run(
    action_id: str,
    handler: Handler,
    args: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> Any:
    return CONNECTOR.action(action_id).run(ctx(handler, options), args)


def test_verify_returns_the_username_and_sends_the_token() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v4/user"
        assert req.headers["PRIVATE-TOKEN"] == "glpat-x"
        return httpx.Response(200, json={"username": "alice", "id": 3})

    assert CONNECTOR.verify is not None
    assert CONNECTOR.verify(ctx(handler)).account_label == "alice"


def test_default_base_url_is_gitlab_com() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(200, json={"username": "a"})

    secrets = ConnectionSecrets(base_url=None, username=None, token="t")
    assert CONNECTOR.verify is not None
    CONNECTOR.verify(ConnectorContext(secrets, {}, transport=httpx.MockTransport(handler)))
    assert seen == ["https://gitlab.com/api/v4/user"]


def test_project_path_is_url_encoded_and_falls_back_to_the_node_option() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.raw_path.startswith(b"/api/v4/projects/group%2Fapp/merge_requests")
        assert req.url.params["state"] == "opened"
        return httpx.Response(
            200,
            json=[
                {
                    "iid": 7,
                    "title": "Fix login",
                    "state": "opened",
                    "author": {"username": "bob"},
                    "source_branch": "fix",
                    "target_branch": "main",
                    "web_url": "https://gitlab.test/mr/7",
                    "labels": ["bug"],
                    "updated_at": "2026-10-01T00:00:00Z",
                }
            ],
        )

    result = run("list_merge_requests", handler, {}, {"project": "group/app"})
    assert result == [
        {
            "iid": 7,
            "title": "Fix login",
            "state": "opened",
            "author": "bob",
            "source_branch": "fix",
            "target_branch": "main",
            "labels": ["bug"],
            "updated_at": "2026-10-01T00:00:00Z",
            "url": "https://gitlab.test/mr/7",
        }
    ]


def test_an_action_without_a_project_says_so() -> None:
    with pytest.raises(ConnectorError, match="project"):
        run("list_issues", lambda req: httpx.Response(200, json=[]), {})


def test_merge_request_changes_are_capped() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/merge_requests/7/diffs")
        return httpx.Response(200, json=[{"new_path": "a.py", "diff": "+" * 5000}] * 3)

    result = run(
        "get_merge_request_changes", handler, {"project": "g/a", "iid": 7, "max_chars": 6000}
    )
    assert result["truncated"] is True
    assert sum(len(f["diff"]) for f in result["files"]) <= 6000


def test_create_issue_posts_labels_as_a_comma_list() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        body = json.loads(req.content)
        assert body == {"title": "Crash", "description": "Steps", "labels": "bug,urgent"}
        return httpx.Response(
            201, json={"iid": 12, "web_url": "https://gitlab.test/i/12", "title": "Crash"}
        )

    result = run(
        "create_issue",
        handler,
        {"project": "g/a", "title": "Crash", "description": "Steps", "labels": ["bug", "urgent"]},
    )
    assert result == {"iid": 12, "title": "Crash", "url": "https://gitlab.test/i/12"}


def test_add_merge_request_note_posts_the_body() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/merge_requests/7/notes")
        assert json.loads(req.content) == {"body": "Looks good"}
        return httpx.Response(201, json={"id": 99})

    assert run(
        "add_merge_request_note", handler, {"project": "g/a", "iid": 7, "body": "Looks good"}
    ) == {"note_id": 99}


def test_get_file_returns_text_at_a_ref() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.raw_path.startswith(
            b"/api/v4/projects/g%2Fa/repository/files/src%2Fmain.py/raw"
        )
        assert req.url.params["ref"] == "main"
        return httpx.Response(200, text="print('hi')")

    assert (
        run("get_file", handler, {"project": "g/a", "file_path": "src/main.py", "ref": "main"})
        == "print('hi')"
    )


def test_reads_are_read_and_writes_are_writes() -> None:
    kinds = {action.id: action.kind for action in CONNECTOR.actions}
    assert kinds["list_merge_requests"] == "read"
    assert kinds["create_issue"] == "write"
    assert not any(
        word in action_id for action_id in kinds for word in ("merge_merge", "approve", "delete")
    )
