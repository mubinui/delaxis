"""Append-only, queryable audit trail.

``src.audit_logging`` already emits structured events, but only outward into
structlog — nothing can read them back. Compliance questions ("who changed this
workflow, and when") and the Studio's audit viewer both need a store you can
query, so this module adds one: a small SQLite table beside the other ``data/``
state.

Two properties make it an audit trail rather than a log table:

* **Append-only.** There is no update or delete entrypoint. Records go in and
  stay in.
* **Hash-chained.** Each row carries ``prev_hash`` and its own ``entry_hash``
  over the record's content. Editing or dropping a row breaks every hash after
  it, and :func:`verify_audit_chain` reports where. That detects tampering; it
  does not prevent it — file permissions and backups still do that work.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config.env_compat import env

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LOCK = threading.Lock()

GENESIS_HASH = "0" * 64

# Severity ordering used by the ``min_severity`` query filter.
SEVERITIES: tuple[str, ...] = ("debug", "info", "notice", "warning", "error", "critical")

# Free-form, but these are what the platform emits, so the viewer can group them.
KNOWN_CATEGORIES: tuple[str, ...] = (
    "config",
    "auth",
    "workflow",
    "agent",
    "tool",
    "data_access",
    "security",
    "deployment",
    "custom",
)


def audit_db_path() -> Path:
    """Location of the audit database, honouring the DELAXIS_DATA_DIR override."""
    default = str(_PROJECT_ROOT / "data")
    data_dir = Path(env("DELAXIS_DATA_DIR", default) or default)
    return data_dir / "audit_trail.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_entries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    category     TEXT NOT NULL,
    action       TEXT NOT NULL,
    actor        TEXT,
    resource     TEXT,
    outcome      TEXT NOT NULL,
    severity     TEXT NOT NULL,
    detail       TEXT,
    session_id   TEXT,
    workflow_id  TEXT,
    prev_hash    TEXT NOT NULL,
    entry_hash   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_entries(ts);
CREATE INDEX IF NOT EXISTS idx_audit_category ON audit_entries(category);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_entries(actor);
CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_entries(resource);
"""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = audit_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10.0)
    connection.row_factory = sqlite3.Row
    try:
        # WAL keeps the API's readers from blocking a concurrent append.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(_SCHEMA)
        yield connection
        connection.commit()
    finally:
        connection.close()


def _hash_entry(record: dict[str, Any], prev_hash: str) -> str:
    """Hash over the canonical record plus the previous link."""
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{prev_hash}{payload}".encode()).hexdigest()


def _current_actor() -> str | None:
    """Best-effort actor from the request/tool context, falling back to the OS user."""
    try:
        from src.tools.context_utils import get_user_context_info

        info = get_user_context_info()
        username = info.get("username")
        if username:
            return str(username)
    except Exception:
        pass
    return os.environ.get("USER") or os.environ.get("USERNAME")


def append_audit_entry(
    action: str,
    category: str = "custom",
    actor: str | None = None,
    resource: str | None = None,
    outcome: str = "success",
    severity: str = "info",
    detail: dict[str, Any] | None = None,
    session_id: str | None = None,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    """Append one entry and return it. The programmatic entrypoint."""
    if not action or not action.strip():
        raise ValueError("audit entry requires a non-empty 'action'")
    severity = severity.lower().strip()
    if severity not in SEVERITIES:
        raise ValueError(f"unknown severity '{severity}'; use one of {', '.join(SEVERITIES)}")

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "category": category.strip() or "custom",
        "action": action.strip(),
        "actor": actor if actor is not None else _current_actor(),
        "resource": resource,
        "outcome": outcome,
        "severity": severity,
        "detail": json.dumps(detail, sort_keys=True, default=str) if detail else None,
        "session_id": session_id,
        "workflow_id": workflow_id,
    }

    # The read of the tail and the write of the new row must be atomic, or two
    # concurrent appends chain off the same prev_hash and the chain forks.
    with _LOCK, _connect() as connection:
        row = connection.execute(
            "SELECT entry_hash FROM audit_entries ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_hash = row["entry_hash"] if row else GENESIS_HASH
        entry_hash = _hash_entry(record, prev_hash)
        cursor = connection.execute(
            """
            INSERT INTO audit_entries
                (ts, category, action, actor, resource, outcome, severity,
                 detail, session_id, workflow_id, prev_hash, entry_hash)
            VALUES (:ts, :category, :action, :actor, :resource, :outcome, :severity,
                    :detail, :session_id, :workflow_id, :prev_hash, :entry_hash)
            """,
            {**record, "prev_hash": prev_hash, "entry_hash": entry_hash},
        )
        entry_id = cursor.lastrowid

    return {**record, "id": entry_id, "prev_hash": prev_hash, "entry_hash": entry_hash}


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    entry = dict(row)
    if entry.get("detail"):
        try:
            entry["detail"] = json.loads(entry["detail"])
        except (json.JSONDecodeError, TypeError):
            pass
    return entry


def read_audit_entries(
    category: str | None = None,
    actor: str | None = None,
    resource: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    min_severity: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query the trail, newest first. The programmatic entrypoint."""
    clauses: list[str] = []
    params: dict[str, Any] = {}

    for column, value in (
        ("category", category),
        ("actor", actor),
        ("outcome", outcome),
    ):
        if value:
            clauses.append(f"{column} = :{column}")
            params[column] = value

    # Resource and action are matched as prefixes so "workflow:" finds every
    # workflow resource without the caller knowing each full id.
    for column, value in (("resource", resource), ("action", action)):
        if value:
            clauses.append(f"{column} LIKE :{column}")
            params[column] = f"{value}%"

    if min_severity:
        wanted = min_severity.lower().strip()
        if wanted not in SEVERITIES:
            raise ValueError(f"unknown severity '{min_severity}'")
        allowed = SEVERITIES[SEVERITIES.index(wanted) :]
        placeholders = ", ".join(f":sev{index}" for index in range(len(allowed)))
        clauses.append(f"severity IN ({placeholders})")
        params.update({f"sev{index}": name for index, name in enumerate(allowed)})

    if since:
        clauses.append("ts >= :since")
        params["since"] = since
    if until:
        clauses.append("ts <= :until")
        params["until"] = until

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params["limit"] = max(1, min(int(limit), 500))
    params["offset"] = max(0, int(offset))

    with _connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM audit_entries {where} ORDER BY id DESC LIMIT :limit OFFSET :offset",
            params,
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def verify_audit_chain(limit: int | None = None) -> dict[str, Any]:
    """Recompute the hash chain and report the first break, if any."""
    with _connect() as connection:
        query = "SELECT * FROM audit_entries ORDER BY id ASC"
        if limit:
            query += f" LIMIT {max(1, int(limit))}"
        rows = connection.execute(query).fetchall()

    expected_prev = GENESIS_HASH
    for row in rows:
        record = {
            "ts": row["ts"],
            "category": row["category"],
            "action": row["action"],
            "actor": row["actor"],
            "resource": row["resource"],
            "outcome": row["outcome"],
            "severity": row["severity"],
            "detail": row["detail"],
            "session_id": row["session_id"],
            "workflow_id": row["workflow_id"],
        }
        if row["prev_hash"] != expected_prev:
            return {
                "valid": False,
                "checked": len(rows),
                "broken_at_id": row["id"],
                "reason": "prev_hash does not match the preceding entry — a row was altered or removed",
            }
        recomputed = _hash_entry(record, expected_prev)
        if recomputed != row["entry_hash"]:
            return {
                "valid": False,
                "checked": len(rows),
                "broken_at_id": row["id"],
                "reason": "entry_hash does not match the record content — this row was altered",
            }
        expected_prev = row["entry_hash"]

    return {"valid": True, "checked": len(rows), "head_hash": expected_prev}


def audit_statistics() -> dict[str, Any]:
    """Counts by category, outcome and severity, for the Studio dashboard."""
    with _connect() as connection:
        total = connection.execute("SELECT COUNT(*) AS n FROM audit_entries").fetchone()["n"]
        by = {}
        for column in ("category", "outcome", "severity"):
            rows = connection.execute(
                f"SELECT {column} AS key, COUNT(*) AS n FROM audit_entries GROUP BY {column}"
            ).fetchall()
            by[column] = {row["key"]: row["n"] for row in rows}
        span = connection.execute(
            "SELECT MIN(ts) AS first_ts, MAX(ts) AS last_ts FROM audit_entries"
        ).fetchone()

    return {
        "total": total,
        "by_category": by["category"],
        "by_outcome": by["outcome"],
        "by_severity": by["severity"],
        "first_entry": span["first_ts"],
        "last_entry": span["last_ts"],
    }


# --------------------------------------------------------------------------- #
# Tool entrypoints
# --------------------------------------------------------------------------- #


def record_audit_event(
    action: str,
    category: str = "custom",
    resource: str = "",
    outcome: str = "success",
    severity: str = "info",
    detail: str = "",
) -> str:
    """
    Write an entry to the tamper-evident audit trail.

    Use this to record a decision or an action that someone may need to account
    for later — an approval, a data access, a policy exception. Entries cannot
    be edited or deleted once written.

    Args:
        action: What happened, e.g. "approved_refund" or "exported_customer_list".
        category: One of config, auth, workflow, agent, tool, data_access,
            security, deployment, custom.
        resource: What was acted on, e.g. "order:12345".
        outcome: "success", "failure", or "denied".
        severity: debug, info, notice, warning, error, or critical.
        detail: Optional JSON object (or plain text) with supporting context.

    Returns:
        JSON with the stored entry's id, timestamp, and hash.
    """
    parsed: dict[str, Any] | None = None
    if detail:
        try:
            loaded = json.loads(detail)
            parsed = loaded if isinstance(loaded, dict) else {"value": loaded}
        except json.JSONDecodeError:
            parsed = {"note": detail}

    try:
        entry = append_audit_entry(
            action=action,
            category=category,
            resource=resource or None,
            outcome=outcome,
            severity=severity,
            detail=parsed,
        )
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        return json.dumps({"error": f"Could not write audit entry: {exc}"})

    return json.dumps(
        {
            "recorded": True,
            "id": entry["id"],
            "ts": entry["ts"],
            "entry_hash": entry["entry_hash"],
        }
    )


def query_audit_log(
    category: str = "",
    actor: str = "",
    resource: str = "",
    action: str = "",
    outcome: str = "",
    min_severity: str = "",
    since: str = "",
    limit: int = 20,
) -> str:
    """
    Search the audit trail and return matching entries, newest first.

    Args:
        category: Filter by category (config, auth, workflow, data_access, ...).
        actor: Filter by exact actor/username.
        resource: Prefix match on the resource, e.g. "order:" matches every order.
        action: Prefix match on the action name.
        outcome: "success", "failure", or "denied".
        min_severity: Return this severity and above (debug < info < notice <
            warning < error < critical).
        since: ISO-8601 lower bound, e.g. "2026-08-01T00:00:00+00:00".
        limit: Maximum entries to return (1-500, default 20).

    Returns:
        JSON: {"count": int, "entries": [...]}
    """
    try:
        entries = read_audit_entries(
            category=category or None,
            actor=actor or None,
            resource=resource or None,
            action=action or None,
            outcome=outcome or None,
            min_severity=min_severity or None,
            since=since or None,
            limit=limit,
        )
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        return json.dumps({"error": f"Could not read audit trail: {exc}"})

    return json.dumps({"count": len(entries), "entries": entries}, indent=2, default=str)


def verify_audit_integrity() -> str:
    """
    Check the audit trail's hash chain and report whether any entry was altered.

    Returns:
        JSON: {"valid": bool, "checked": int, ...} — when invalid, "broken_at_id"
        names the first entry that fails verification.
    """
    try:
        return json.dumps(verify_audit_chain(), indent=2)
    except Exception as exc:
        return json.dumps({"error": f"Could not verify audit trail: {exc}"})
