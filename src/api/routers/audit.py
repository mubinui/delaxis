"""Audit trail and security endpoints.

Backs the Studio's audit viewer and its ad-hoc scanner. Reads and scans only —
there is deliberately no write endpoint, because entries should come from the
code path that performed the action, not from whoever can reach the API.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.audit_logging import get_logger
from src.tools.audit_trail import (
    KNOWN_CATEGORIES,
    SEVERITIES,
    audit_statistics,
    read_audit_entries,
    verify_audit_chain,
)
from src.tools.security import find_injection_signals, find_secrets, security_scan

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("/entries")
async def list_entries(
    category: str | None = Query(None),
    actor: str | None = Query(None),
    resource: str | None = Query(None, description="Prefix match, e.g. 'workflow:'"),
    action: str | None = Query(None, description="Prefix match on the action name"),
    outcome: str | None = Query(None),
    min_severity: str | None = Query(None),
    since: str | None = Query(None, description="ISO-8601 lower bound"),
    until: str | None = Query(None, description="ISO-8601 upper bound"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Query the audit trail, newest first."""
    try:
        entries = read_audit_entries(
            category=category,
            actor=actor,
            resource=resource,
            action=action,
            outcome=outcome,
            min_severity=min_severity,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("audit_query_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Audit trail could not be read: {exc}",
        ) from exc

    return {
        "count": len(entries),
        "entries": entries,
        "categories": list(KNOWN_CATEGORIES),
        "severities": list(SEVERITIES),
    }


@router.get("/stats")
async def stats() -> dict[str, Any]:
    """Counts by category, outcome and severity, for the dashboard header."""
    try:
        return audit_statistics()
    except Exception as exc:
        logger.error("audit_stats_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Audit statistics could not be computed: {exc}",
        ) from exc


@router.get("/verify")
async def verify() -> dict[str, Any]:
    """Recompute the hash chain and report whether any entry was altered."""
    try:
        return verify_audit_chain()
    except Exception as exc:
        logger.error("audit_verify_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Audit trail could not be verified: {exc}",
        ) from exc


class ScanRequest(BaseModel):
    text: str = Field(description="Content to scan")
    checks: str = Field(
        default="secrets,injection,pii",
        description="Comma-separated subset of secrets, injection, pii",
    )


@router.post("/scan")
async def scan(body: ScanRequest) -> dict[str, Any]:
    """Run the security scanner over a piece of text and return the verdict."""
    result = json.loads(security_scan(body.text, body.checks))
    if "error" in result:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return result


@router.post("/scan/secrets")
async def scan_secrets(body: ScanRequest) -> dict[str, Any]:
    """Secret-scan only, for a fast inline check in the editor."""
    findings = find_secrets(body.text)
    return {"clean": not findings, "count": len(findings), "findings": findings}


@router.post("/scan/injection")
async def scan_injection(body: ScanRequest) -> dict[str, Any]:
    """Prompt-injection check only."""
    return find_injection_signals(body.text)
