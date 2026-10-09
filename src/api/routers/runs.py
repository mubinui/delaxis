"""Run history: list, inspect, replay and delete recorded workflow runs.

Every run that goes through the session manager is recorded, whatever started
it (chat, the Studio canvas, a deployment, a test case). A record keeps the
request, the outcome and every event the run streamed, so the Studio can play
it back on the canvas or run the same request again against the workflow as
it is now.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from src.api.session_manager import get_session_manager
from src.audit_logging import get_logger
from src.infrastructure.database.run_store import RUN_STATUSES, get_run_store

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


class ReplayRequest(BaseModel):
    """Optional changes for a replay; by default the recorded request is sent as it was."""

    message: str | None = Field(
        default=None, min_length=1, description="Send this instead of the recorded message"
    )


def _load(run_id: UUID, *, with_events: bool = True) -> dict[str, Any]:
    record = get_run_store().get(run_id, with_events=with_events)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Run not found: {run_id}"
        )
    return record


@router.get("")
async def list_runs(
    workflow_id: str | None = Query(None),
    run_status: str | None = Query(
        None, alias="status", description="running, succeeded or failed"
    ),
    source: str | None = Query(None, description="chat, test, deployment, replay, ..."),
    session_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List recorded runs, newest first. Event logs are left out; fetch a run for them."""
    if run_status and run_status not in RUN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of {', '.join(RUN_STATUSES)}",
        )
    items, total = await asyncio.to_thread(
        get_run_store().list,
        workflow_id=workflow_id,
        status=run_status,
        source=source,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{run_id}")
async def get_run(run_id: UUID) -> dict[str, Any]:
    """One run, with its full event log."""
    return await asyncio.to_thread(_load, run_id)


@router.post("/{run_id}/replay")
async def replay_run(run_id: UUID, body: ReplayRequest | None = None) -> dict[str, Any]:
    """Send a recorded request to the workflow again, in a fresh session.

    The replay runs the workflow as it is configured now, so it shows what a
    change to an agent or a prompt does to a request that was seen before. The
    response is the new run's record, including when the replay failed.
    """
    original = await asyncio.to_thread(_load, run_id, with_events=False)
    manager = get_session_manager()
    try:
        session = await manager.create_session(
            workflow_id=original["workflow_id"],
            user_id=original.get("user_id") or "replay",
            metadata={"source": "replay", "replay_of": str(run_id)},
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot replay: {exc}. The workflow this run used no longer exists.",
        ) from exc

    message = body.message if body and body.message else original["message"]
    try:
        await manager.process_message(
            session.session_id, message, metadata={"replay_of": str(run_id)}
        )
    except Exception as exc:
        logger.warning("run_replay_failed", run_id=str(run_id), error=str(exc))

    replays, _ = await asyncio.to_thread(
        get_run_store().list, session_id=str(session.session_id), limit=1
    )
    if not replays:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The replay ran but was not recorded; check the server log.",
        )
    return await asyncio.to_thread(_load, UUID(replays[0]["id"]))


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: UUID) -> Response:
    """Remove a run from the history."""
    if not await asyncio.to_thread(get_run_store().delete, run_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Run not found: {run_id}"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
