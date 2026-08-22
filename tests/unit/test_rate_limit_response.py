"""The throttle must report itself as a throttle.

An HTTPException raised inside an ``app.middleware("http")`` function never
reaches FastAPI's exception handlers, so every throttled request was answered
with 500 INTERNAL_SERVER_ERROR. A client cannot back off from that: it looks
like the server broke, not like it asked you to slow down.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.app_factory import create_app
from src.api.rate_limiting import rate_limiting_middleware


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DELAXIS_DATA_DIR", str(tmp_path))
    rate_limiting_middleware._rate_limit_store.clear()
    yield TestClient(create_app())
    rate_limiting_middleware._rate_limit_store.clear()


@pytest.fixture
def throttled(monkeypatch):
    """Squeeze the limit down so a couple of requests trip it."""
    settings = rate_limiting_middleware.settings
    monkeypatch.setattr(settings.security, "requests_per_minute", 2, raising=False)
    monkeypatch.setattr(settings.security, "requests_per_hour", 1000, raising=False)


def exhaust(client, path="/api/v1/tools", attempts=8):
    """Hit an endpoint until it is throttled; return the throttled response."""
    for _ in range(attempts):
        response = client.get(path)
        if response.status_code == 429:
            return response
    return None


class TestThrottleResponse:
    def test_returns_429_not_500(self, client, throttled):
        response = exhaust(client)
        assert response is not None, "the limit never tripped"
        assert response.status_code == 429

    def test_sets_retry_after(self, client, throttled):
        # Without this header a client has nothing to back off against.
        response = exhaust(client)
        assert response.headers.get("Retry-After") == "60"

    def test_body_names_the_actual_problem(self, client, throttled):
        body = exhaust(client).json()
        assert body["error_code"] == "RATE_LIMIT_EXCEEDED"
        assert "rate limit exceeded" in body["error_message"].lower()

    def test_body_says_which_limit_was_hit(self, client, throttled):
        details = exhaust(client).json()["details"]
        assert details["window"] == "minute"
        assert details["limit"] == 2
        assert details["retry_after_seconds"] == 60

    def test_body_matches_the_platform_error_shape(self, client, throttled):
        body = exhaust(client).json()
        for key in ("error_code", "error_message", "error_type", "request_id", "timestamp"):
            assert key in body, f"missing {key}"

    def test_no_500_is_ever_produced_by_throttling(self, client, throttled):
        statuses = {client.get("/api/v1/tools").status_code for _ in range(8)}
        assert 500 not in statuses, f"throttling produced a 500: {statuses}"
        assert 429 in statuses


class TestNormalTraffic:
    def test_requests_under_the_limit_pass(self, client):
        assert client.get("/api/v1/tools").status_code == 200

    def test_health_is_never_throttled(self, client, throttled):
        # Liveness probes must not be able to throttle themselves out of service.
        for _ in range(12):
            assert client.get("/health").status_code != 429
