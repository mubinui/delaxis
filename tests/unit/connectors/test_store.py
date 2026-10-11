"""Connections persist encrypted, list without secrets, and include Gmail accounts."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.connectors.store import ConnectionStore
from src.infrastructure.database.connection import get_db_manager
from src.infrastructure.database.schema import IntegrationCredential


@pytest.fixture(autouse=True)
def empty_table() -> Iterator[None]:
    with get_db_manager().get_session() as session:
        session.query(IntegrationCredential).delete()
    yield


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.fernet import Fernet

    import src.infrastructure.secrets as secrets_module

    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(secrets_module, "_credential_manager", None)


def make(store: ConnectionStore, **overrides: object) -> str:
    data: dict[str, object] = {
        "connector": "gitlab",
        "base_url": "https://gitlab.test",
        "username": None,
        "token": "glpat-secret",
        "account_label": "alice",
        "options": {},
    }
    data.update(overrides)
    return store.create(**data).id  # type: ignore[arg-type]


def test_a_connection_round_trips_and_its_token_is_encrypted() -> None:
    store = ConnectionStore()
    connection_id = make(
        store, username="ops@acme.test", options={"api_version": "3"}, connector="jira"
    )
    listed = store.list_connections()
    assert [c.connector for c in listed] == ["jira"]
    assert "token" not in listed[0].to_dict()
    secrets = store.secrets(connection_id)
    assert secrets is not None
    assert (secrets.token, secrets.username, secrets.options) == (
        "glpat-secret",
        "ops@acme.test",
        {"api_version": "3"},
    )
    with get_db_manager().get_session() as session:
        row = session.query(IntegrationCredential).one()
        assert "glpat-secret" not in row.encrypted_token


def test_list_filters_by_connector() -> None:
    store = ConnectionStore()
    make(store)
    make(store, connector="jira")
    assert [c.connector for c in store.list_connections("jira")] == ["jira"]


def test_gmail_accounts_show_up_as_oauth_connections() -> None:
    with get_db_manager().get_session() as session:
        session.add(
            IntegrationCredential(
                provider="gmail", account_email="ops@acme.test", encrypted_token="x", scopes=[]
            )
        )
    connection = ConnectionStore().list_connections("gmail")[0]
    assert (connection.auth_kind, connection.account_label) == ("oauth", "ops@acme.test")
    secrets = ConnectionStore().secrets(connection.id)
    assert secrets is not None and secrets.account_label == "ops@acme.test"
    assert secrets.token == ""


def test_record_test_and_delete() -> None:
    store = ConnectionStore()
    connection_id = make(store)
    store.record_test(connection_id, ok=False, error="401")
    connection = store.get(connection_id)
    assert connection is not None
    assert (connection.last_status, connection.last_error) == ("failed", "401")
    store.record_test(connection_id, ok=True, account_label="alice2")
    connection = store.get(connection_id)
    assert connection is not None
    assert (connection.last_status, connection.last_error, connection.account_label) == (
        "ok",
        None,
        "alice2",
    )
    assert store.delete(connection_id) is True
    assert store.get(connection_id) is None
    assert store.delete(connection_id) is False


def test_unknown_or_malformed_ids_are_none() -> None:
    store = ConnectionStore()
    assert store.get("00000000-0000-0000-0000-000000000000") is None
    assert store.get("not-a-uuid") is None
    assert store.secrets("not-a-uuid") is None
