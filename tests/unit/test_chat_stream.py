"""Tests for streaming chat event contracts and routes."""

from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi.testclient import TestClient

from src.api.auth import CurrentUser, UserRole, require_user
from src.api.main import app
from src.core.events import ResponseDeltaType, StreamEventBuilder


def test_response_delta_serializes_as_sse_frame() -> None:
    """ResponseDelta should emit a valid Server-Sent Events frame."""
    builder = StreamEventBuilder("session-1", correlation_id="request-1")
    delta = builder.delta(ResponseDeltaType.TOKEN, {"content": "hello"}, agent_id="agent-1")

    frame = delta.to_sse()

    assert frame.startswith("event: token\n")
    assert '"type":"token"' in frame
    assert '"session_id":"session-1"' in frame
    assert '"sequence":0' in frame
    assert '"content":"hello"' in frame
    assert frame.endswith("\n\n")


def test_stream_chat_route_returns_ordered_sse_events(monkeypatch) -> None:
    """The SSE route should stream the SessionManager deltas in order."""
    session_id = uuid4()
    builder = StreamEventBuilder(str(session_id), correlation_id="test-request")

    async def fake_stream_message(**kwargs) -> AsyncIterator:
        assert kwargs["session_id"] == session_id
        assert kwargs["message"] == "hello"
        yield builder.delta(ResponseDeltaType.START)
        yield builder.delta(ResponseDeltaType.TOKEN, {"content": "Hi"}, agent_id="assistant")
        yield builder.delta(
            ResponseDeltaType.DONE,
            {
                "result": {
                    "session_id": str(session_id),
                    "response": "Hi",
                    "turn_count": 1,
                    "chat_history": [],
                    "summary": "",
                    "safety_passed": True,
                    "cost": {},
                    "metadata": {},
                }
            },
        )

    class FakeSessionManager:
        stream_message = staticmethod(fake_stream_message)

    mock_user = CurrentUser(
        user_id=uuid4(),
        username="test_user",
        role=UserRole.USER,
        roles=["user"],
        auth_method="test",
        raw_token="test-token",
    )

    monkeypatch.setattr(
        "src.api.routers.chat_stream.get_session_manager",
        lambda: FakeSessionManager(),
    )
    app.dependency_overrides[require_user] = lambda: mock_user

    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/chat/stream",
            json={"sessionId": str(session_id), "query": "hello"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("event: ") == 3
    assert "event: start" in response.text
    assert "event: token" in response.text
    assert "event: done" in response.text
    assert '"sequence":0' in response.text
    assert '"sequence":1' in response.text
    assert '"sequence":2' in response.text


def test_stream_chat_route_rejects_invalid_session_id(monkeypatch) -> None:
    """Invalid session IDs should fail before creating a stream."""
    mock_user = CurrentUser(
        user_id=uuid4(),
        username="test_user",
        role=UserRole.USER,
        roles=["user"],
        auth_method="test",
    )

    app.dependency_overrides[require_user] = lambda: mock_user

    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/chat/stream",
            json={"sessionId": "not-a-uuid", "query": "hello"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"]["error_code"] == "INVALID_SESSION_ID"
