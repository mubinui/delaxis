"""Streaming chat endpoints for real-time agent responses."""

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse

from src.api.auth import CurrentUser, require_user
from src.api.context import set_request_user
from src.api.models import QueryRequest
from src.api.session_manager import get_session_manager
from src.audit_logging import get_logger
from src.tools.context_utils import clear_tool_execution_context, set_tool_execution_context

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/chat", tags=["chat-stream"])


def _parse_session_id(raw_session_id: str, request_id: str | None = None) -> UUID:
    """Parse a user-provided session ID into a UUID."""
    try:
        return UUID(raw_session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_SESSION_ID",
                "error_message": f"Invalid session ID format: {raw_session_id}",
                "error_type": "ValueError",
                "request_id": request_id,
                "session_id": raw_session_id,
            },
        ) from None


def _set_stream_context(current_user: CurrentUser) -> None:
    """Set user context for tools during streamed execution."""
    set_request_user(current_user)
    set_tool_execution_context(
        username=current_user.username,
        roles=current_user.roles,
        raw_token=current_user.raw_token,
    )


@router.post("/stream")
async def stream_chat(
    request: Request,
    body: QueryRequest,
    current_user: CurrentUser = Depends(require_user),
) -> StreamingResponse:
    """Stream chat response deltas using Server-Sent Events."""
    request_id = getattr(request.state, "request_id", None)
    session_id = _parse_session_id(body.session_id, request_id=request_id)
    _set_stream_context(current_user)

    logger.info(
        "stream_chat_started",
        request_id=request_id,
        session_id=session_id,
        username=current_user.username,
    )

    async def event_stream() -> AsyncIterator[str]:
        try:
            session_manager = get_session_manager()
            async for delta in session_manager.stream_message(
                session_id=session_id,
                message=body.query,
                max_turns=body.max_turns,
                metadata=body.metadata,
                correlation_id=request_id,
            ):
                yield delta.to_sse()
        finally:
            clear_tool_execution_context()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("/ws")
async def stream_chat_websocket(websocket: WebSocket) -> None:
    """Stream chat response deltas over a WebSocket connection."""
    await websocket.accept()
    try:
        payload = await websocket.receive_json()
        body = QueryRequest(**payload)
        session_id = UUID(body.session_id)
        session_manager = get_session_manager()

        async for delta in session_manager.stream_message(
            session_id=session_id,
            message=body.query,
            max_turns=body.max_turns,
            metadata=body.metadata,
        ):
            await websocket.send_json(delta.model_dump(mode="json"))
    except WebSocketDisconnect:
        logger.info("stream_chat_websocket_disconnected")
    except Exception as exc:
        logger.error("stream_chat_websocket_failed", error=str(exc), exc_info=True)
        await websocket.send_json(
            {
                "type": "error",
                "payload": {
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            }
        )
    finally:
        clear_tool_execution_context()
