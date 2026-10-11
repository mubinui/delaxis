"""The one HTTP call every connector makes.

Errors become sentences a user can act on ("GitLab rejected the token")
instead of status codes, and a 429 is retried once, honouring Retry-After up
to five seconds, before it is reported.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from src.connectors.base import ConnectorContext, ConnectorError

_MAX_RETRY_WAIT_SECONDS = 5.0


def _remote_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300].strip()
    if isinstance(body, dict):
        for key in ("errorMessages", "message", "error", "errors", "error_description"):
            value = body.get(key)
            if isinstance(value, list) and value:
                return "; ".join(str(item) for item in value)
            if isinstance(value, dict) and value:
                return "; ".join(f"{k}: {v}" for k, v in value.items())
            if value:
                return str(value)
    return str(body)[:300]


def _raise_for(response: httpx.Response, service: str) -> None:
    status = response.status_code
    remote = _remote_message(response)
    if status == 401:
        raise ConnectorError(
            f"{service} rejected the token (401). Check the connection on the Connections page.",
            status,
        )
    if status == 403:
        raise ConnectorError(
            f"The {service} account lacks permission for this ({remote or '403'}).", status
        )
    if status == 404:
        raise ConnectorError(f"{service}: not found ({remote or response.request.url}).", status)
    if status == 429:
        raise ConnectorError(f"{service} is rate limiting requests; try again shortly.", status)
    raise ConnectorError(f"{service} returned {status}: {remote or 'no detail'}", status)


def request(
    ctx: ConnectorContext,
    method: str,
    url: str,
    *,
    service: str,
    headers: dict[str, str] | None = None,
    auth: httpx.Auth | tuple[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    raw: bool = False,
    timeout: float = 30.0,
) -> Any:
    """Call ``url`` and return its JSON (or text when ``raw``), or raise ConnectorError."""
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    with httpx.Client(transport=ctx.transport, timeout=timeout, auth=auth) as client:
        response: httpx.Response | None = None
        for attempt in (1, 2):
            try:
                response = client.request(
                    method,
                    url,
                    headers={"Accept": "application/json", **(headers or {})},
                    params=clean_params,
                    json=json_body,
                )
            except httpx.TransportError as exc:
                raise ConnectorError(f"Could not reach {url}: {exc}") from exc
            if response.status_code == 429 and attempt == 1:
                try:
                    wait = float(response.headers.get("Retry-After", "1"))
                except ValueError:
                    wait = 1.0
                time.sleep(min(max(wait, 0.0), _MAX_RETRY_WAIT_SECONDS))
                continue
            break
    assert response is not None
    if response.status_code >= 400:
        _raise_for(response, service)
    if raw:
        return response.text
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return response.text
