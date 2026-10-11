"""Connections: accounts on remote systems, stored with their secrets encrypted.

A connection is a row of integration_credentials. Token connections (Jira,
GitLab) keep {"token", "username"} Fernet-encrypted; Gmail rows come from the
Google sign-in flow and are listed here as OAuth connections. Nothing this
module returns to callers outside the runtime contains a secret.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import UUID

from src.connectors.base import ConnectionSecrets
from src.infrastructure.database.connection import get_db_manager
from src.infrastructure.database.schema import IntegrationCredential
from src.infrastructure.secrets import get_global_credential_manager
from src.utils.time import as_utc, utc_now_naive


@dataclass
class Connection:
    id: str
    connector: str
    account_label: str | None
    base_url: str | None
    auth_kind: str
    options: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    last_verified_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(value: Any) -> str | None:
    aware = as_utc(value)
    return aware.isoformat() if aware else None


def _connection(row: IntegrationCredential) -> Connection:
    return Connection(
        id=str(row.id),
        connector=row.provider,
        account_label=row.account_label or row.account_email,
        base_url=row.base_url,
        auth_kind=row.auth_kind or "oauth",
        options=dict(row.options or {}),
        created_at=_iso(row.created_at),
        last_status=row.last_status,
        last_error=row.last_error,
        last_verified_at=_iso(row.last_verified_at),
    )


def _uuid(connection_id: str) -> UUID | None:
    try:
        return UUID(str(connection_id))
    except ValueError:
        return None


class ConnectionStore:
    def __init__(self) -> None:
        self._db = get_db_manager()

    def list_connections(self, connector: str | None = None) -> list[Connection]:
        with self._db.get_session() as session:
            query = session.query(IntegrationCredential)
            if connector:
                query = query.filter(IntegrationCredential.provider == connector)
            rows = query.order_by(IntegrationCredential.created_at).all()
            return [_connection(row) for row in rows]

    def get(self, connection_id: str) -> Connection | None:
        key = _uuid(connection_id)
        if key is None:
            return None
        with self._db.get_session() as session:
            row = session.get(IntegrationCredential, key)
            return _connection(row) if row else None

    def create(
        self,
        *,
        connector: str,
        base_url: str | None,
        username: str | None,
        token: str,
        account_label: str,
        options: dict[str, Any],
    ) -> Connection:
        encrypted = get_global_credential_manager().encrypt_credential(
            json.dumps({"token": token, "username": username})
        )
        with self._db.get_session() as session:
            row = IntegrationCredential(
                provider=connector,
                account_email=None,
                account_label=account_label,
                base_url=base_url,
                auth_kind="token",
                options=options,
                encrypted_token=encrypted,
                scopes=[],
                last_status="ok",
                last_verified_at=utc_now_naive(),
            )
            session.add(row)
            session.flush()
            return _connection(row)

    def secrets(self, connection_id: str) -> ConnectionSecrets | None:
        key = _uuid(connection_id)
        if key is None:
            return None
        with self._db.get_session() as session:
            row = session.get(IntegrationCredential, key)
            if row is None:
                return None
            label = row.account_label or row.account_email
            if (row.auth_kind or "oauth") == "oauth":
                return ConnectionSecrets(
                    base_url=row.base_url,
                    username=None,
                    token="",
                    account_label=label,
                    options=dict(row.options or {}),
                )
            payload = json.loads(
                get_global_credential_manager().decrypt_credential(row.encrypted_token)
            )
            return ConnectionSecrets(
                base_url=row.base_url,
                username=payload.get("username"),
                token=str(payload.get("token") or ""),
                account_label=label,
                options=dict(row.options or {}),
            )

    def record_test(
        self,
        connection_id: str,
        *,
        ok: bool,
        error: str | None = None,
        account_label: str | None = None,
    ) -> None:
        key = _uuid(connection_id)
        if key is None:
            return
        with self._db.get_session() as session:
            row = session.get(IntegrationCredential, key)
            if row is None:
                return
            row.last_status = "ok" if ok else "failed"
            row.last_error = None if ok else error
            row.last_verified_at = utc_now_naive()
            if ok and account_label:
                row.account_label = account_label

    def delete(self, connection_id: str) -> bool:
        key = _uuid(connection_id)
        if key is None:
            return False
        with self._db.get_session() as session:
            row = session.get(IntegrationCredential, key)
            if row is None:
                return False
            session.delete(row)
            return True
