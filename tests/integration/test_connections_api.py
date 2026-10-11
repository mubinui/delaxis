"""The connections API: catalogue, verified create, test, run an action, delete."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from src.connectors import http as connector_http
from src.infrastructure.database.connection import get_db_manager
from src.infrastructure.database.schema import IntegrationCredential


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    import src.infrastructure.secrets as secrets_module

    monkeypatch.setattr(secrets_module, "_credential_manager", None)
    with get_db_manager().get_session() as session:
        session.query(IntegrationCredential).delete()
    yield


@pytest.fixture
def fake_gitlab(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Route every connector HTTP call to a fake GitLab."""
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.headers.get("PRIVATE-TOKEN") != "good":
            return httpx.Response(401, json={"message": "401 Unauthorized"})
        if req.url.path == "/api/v4/user":
            return httpx.Response(200, json={"username": "alice"})
        if req.url.path.endswith("/merge_requests"):
            return httpx.Response(200, json=[{"iid": 7, "title": "Fix login", "web_url": "u"}])
        return httpx.Response(404, json={"message": "404 Not Found"})

    real_client = httpx.Client

    def client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(connector_http.httpx, "Client", client)
    return seen


async def create(client: AsyncClient, **body: Any) -> httpx.Response:
    payload = {"connector": "gitlab", "base_url": "https://gitlab.test", "token": "good", **body}
    return await client.post("/api/v1/integrations/connections", json=payload)


async def test_catalogue_lists_jira_gitlab_and_gmail(async_client: AsyncClient) -> None:
    body = (await async_client.get("/api/v1/integrations/connectors")).json()
    assert [c["id"] for c in body["connectors"]] == ["jira", "gitlab", "gmail"]
    gitlab = body["connectors"][1]
    assert gitlab["auth"]["base_url_default"] == "https://gitlab.com"
    assert {a["kind"] for a in gitlab["actions"]} == {"read", "write"}


async def test_create_verifies_and_never_returns_the_token(
    async_client: AsyncClient, fake_gitlab: list[httpx.Request]
) -> None:
    response = await create(async_client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["account_label"] == "alice" and body["connector"] == "gitlab"
    assert "good" not in response.text
    listed = (await async_client.get("/api/v1/integrations/connections")).json()["connections"]
    assert [c["id"] for c in listed] == [body["id"]]
    assert "good" not in str(listed)


async def test_a_rejected_token_is_not_saved(
    async_client: AsyncClient, fake_gitlab: list[httpx.Request]
) -> None:
    response = await create(async_client, token="bad")
    assert response.status_code == 400
    assert "rejected the token" in response.json()["detail"]
    listed = (await async_client.get("/api/v1/integrations/connections")).json()
    assert listed["connections"] == []


async def test_base_url_is_normalised_and_checked(
    async_client: AsyncClient, fake_gitlab: list[httpx.Request]
) -> None:
    response = await create(async_client, base_url="https://gitlab.test/")
    assert response.json()["base_url"] == "https://gitlab.test"
    bad = await create(async_client, base_url="gitlab.test")
    assert bad.status_code == 400 and "http://" in bad.json()["detail"]
    jira_without_url = await async_client.post(
        "/api/v1/integrations/connections", json={"connector": "jira", "token": "t"}
    )
    assert jira_without_url.status_code == 400
    assert "Jira site URL" in jira_without_url.json()["detail"]


async def test_default_base_url_is_used_when_omitted(
    async_client: AsyncClient, fake_gitlab: list[httpx.Request]
) -> None:
    response = await create(async_client, base_url=None)
    assert response.json()["base_url"] == "https://gitlab.com"


async def test_unknown_connector_and_oauth_connector(async_client: AsyncClient) -> None:
    assert (await create(async_client, connector="nope")).status_code == 404
    gmail = await create(async_client, connector="gmail")
    assert gmail.status_code == 400 and "sign" in gmail.json()["detail"].lower()


async def test_test_endpoint_records_the_outcome(
    async_client: AsyncClient, fake_gitlab: list[httpx.Request]
) -> None:
    connection_id = (await create(async_client)).json()["id"]
    url = f"/api/v1/integrations/connections/{connection_id}/test"
    result = (await async_client.post(url)).json()
    assert result == {"ok": True, "account_label": "alice", "error": None}


async def test_run_action_returns_the_result_and_errors_readably(
    async_client: AsyncClient, fake_gitlab: list[httpx.Request]
) -> None:
    connection_id = (await create(async_client)).json()["id"]
    url = f"/api/v1/integrations/connections/{connection_id}/actions/list_merge_requests"
    ok = await async_client.post(url, json={"args": {}, "options": {"project": "g/a"}})
    assert ok.status_code == 200, ok.text
    assert ok.json()["result"][0]["title"] == "Fix login"
    missing = await async_client.post(url, json={"args": {}, "options": {}})
    assert missing.status_code == 400 and "project" in missing.json()["detail"]
    unknown = await async_client.post(
        f"/api/v1/integrations/connections/{connection_id}/actions/nope", json={}
    )
    assert unknown.status_code == 404


async def test_delete(async_client: AsyncClient, fake_gitlab: list[httpx.Request]) -> None:
    connection_id = (await create(async_client)).json()["id"]
    url = f"/api/v1/integrations/connections/{connection_id}"
    assert (await async_client.delete(url)).status_code == 204
    assert (await async_client.delete(url)).status_code == 404
    assert (await async_client.post(f"{url}/test")).status_code == 404


async def test_connections_require_authentication_and_admin_for_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outside development, anonymous callers are refused and only admins change connections."""
    from httpx import ASGITransport

    from src.api.auth import CurrentUser, UserRole, get_current_user
    from src.api.main import app
    from src.config.settings import get_settings

    monkeypatch.setattr(get_settings().app, "environment", "production")
    base = "/api/v1/integrations"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        assert (await anon.get(f"{base}/connectors")).status_code == 401
        assert (await anon.get(f"{base}/connections")).status_code == 401
        created = await anon.post(f"{base}/connections", json={"connector": "gitlab", "token": "t"})
        assert created.status_code == 401

    user = CurrentUser(
        user_id="00000000-0000-0000-0000-0000000000ee",  # type: ignore[arg-type]
        username="builder",
        role=UserRole.USER,
        auth_method="jwt",
    )
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get(f"{base}/connections")).status_code == 200
            refused = await client.post(
                f"{base}/connections", json={"connector": "gitlab", "token": "t"}
            )
            assert refused.status_code == 403
            missing = "00000000-0000-0000-0000-000000000000"
            assert (await client.delete(f"{base}/connections/{missing}")).status_code == 403
            assert (await client.post(f"{base}/connections/{missing}/test")).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
