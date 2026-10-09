"""An optional RAG service that is not running is reported, not raised as a 503."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from httpx import AsyncClient


async def test_unreachable_rag_service_lists_no_collections_and_says_why(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refuse(self: Any, url: str, **kwargs: Any) -> Any:
        raise httpx.ConnectError("All connection attempts failed")

    monkeypatch.setattr(httpx.AsyncClient, "get", refuse)
    # .request, not .get: the test client is an httpx.AsyncClient too.
    response = await async_client.request("GET", "/api/v1/rag-service/collections")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["collections"] == []
    assert "All connection attempts failed" in body["error"]
    assert body["base_url"].startswith("http")


async def test_reachable_rag_service_passes_its_collections_through(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def answer(self: Any, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200, json={"collections": [{"name": "docs"}]}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", answer)
    body = (await async_client.request("GET", "/api/v1/rag-service/collections")).json()
    assert body == {"available": True, "collections": [{"name": "docs"}]}
