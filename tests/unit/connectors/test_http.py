"""The shared HTTP call: auth, error mapping, and the single 429 retry."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from src.connectors.base import ConnectionSecrets, ConnectorContext, ConnectorError
from src.connectors.http import request

Handler = Callable[[httpx.Request], httpx.Response]


def ctx_for(handler: Handler) -> ConnectorContext:
    secrets = ConnectionSecrets(base_url="https://x.test", username=None, token="t")
    return ConnectorContext(secrets, {}, transport=httpx.MockTransport(handler))


def test_json_is_returned_and_headers_are_sent() -> None:
    seen: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(req.headers)
        return httpx.Response(200, json={"ok": True})

    result = request(
        ctx_for(handler), "GET", "https://x.test/a", service="X", headers={"PRIVATE-TOKEN": "t"}
    )
    assert result == {"ok": True}
    assert seen["private-token"] == "t"


def test_raw_returns_text() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="file body")

    assert (
        request(ctx_for(handler), "GET", "https://x.test/f", service="X", raw=True) == "file body"
    )


def test_empty_body_is_an_empty_dict() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    assert request(ctx_for(handler), "PUT", "https://x.test/a", service="X") == {}


@pytest.mark.parametrize(
    ("status", "words"),
    [(401, "rejected the token"), (403, "permission"), (404, "not found")],
)
def test_common_failures_read_as_sentences(status: int, words: str) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "nope"})

    with pytest.raises(ConnectorError, match=words) as info:
        request(ctx_for(handler), "GET", "https://x.test/a", service="GitLab")
    assert info.value.status == status
    assert "GitLab" in str(info.value)


def test_remote_message_is_passed_through_for_other_errors() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"errorMessages": ["Field 'summary' is required"]})

    with pytest.raises(ConnectorError, match="Field 'summary' is required"):
        request(ctx_for(handler), "POST", "https://x.test/a", service="Jira")


def test_429_is_retried_once_then_reported() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "slow down"})

    with pytest.raises(ConnectorError, match="rate"):
        request(ctx_for(handler), "GET", "https://x.test/a", service="X")
    assert calls["n"] == 2


def test_429_then_success_returns_the_success() -> None:
    responses = [httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json=[1])]

    def handler(req: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    assert request(ctx_for(handler), "GET", "https://x.test/a", service="X") == [1]


def test_unreachable_host_names_the_address() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ConnectorError, match="Could not reach https://x.test/a"):
        request(ctx_for(handler), "GET", "https://x.test/a", service="X")
