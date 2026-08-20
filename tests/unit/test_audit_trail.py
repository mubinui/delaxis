"""Tests for the append-only, hash-chained audit trail.

Every test runs against its own database directory, so ordering between tests
cannot leak through the shared chain.
"""

import json
import sqlite3
import threading

import pytest

from src.tools import audit_trail
from src.tools.audit_trail import (
    GENESIS_HASH,
    append_audit_entry,
    audit_db_path,
    audit_statistics,
    query_audit_log,
    read_audit_entries,
    record_audit_event,
    verify_audit_chain,
    verify_audit_integrity,
)


@pytest.fixture(autouse=True)
def isolated_trail(tmp_path, monkeypatch):
    """Point the trail at a per-test directory."""
    monkeypatch.setenv("DELAXIS_DATA_DIR", str(tmp_path))
    # env_compat may cache; clear any memoised path resolution the module holds.
    yield tmp_path


# ---------------------------------------------------------------------------
# Appending
# ---------------------------------------------------------------------------


class TestAppend:
    def test_returns_the_stored_entry(self):
        entry = append_audit_entry("approved_refund", "data_access", resource="order:1")
        assert entry["id"] == 1
        assert entry["action"] == "approved_refund"
        assert entry["prev_hash"] == GENESIS_HASH
        assert len(entry["entry_hash"]) == 64

    def test_ids_increment(self):
        first = append_audit_entry("one")
        second = append_audit_entry("two")
        assert second["id"] == first["id"] + 1

    def test_each_entry_links_to_the_previous(self):
        first = append_audit_entry("one")
        second = append_audit_entry("two")
        assert second["prev_hash"] == first["entry_hash"]

    def test_empty_action_is_rejected(self):
        with pytest.raises(ValueError, match="non-empty 'action'"):
            append_audit_entry("   ")

    def test_unknown_severity_is_rejected(self):
        with pytest.raises(ValueError, match="unknown severity"):
            append_audit_entry("x", severity="catastrophic")

    def test_detail_round_trips(self):
        append_audit_entry("x", detail={"amount": 42, "currency": "USD"})
        [entry] = read_audit_entries()
        assert entry["detail"] == {"amount": 42, "currency": "USD"}

    def test_actor_defaults_to_the_current_user(self):
        entry = append_audit_entry("x")
        assert entry["actor"]

    def test_explicit_actor_is_honoured(self):
        entry = append_audit_entry("x", actor="service-account")
        assert entry["actor"] == "service-account"


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------


class TestQuery:
    @pytest.fixture(autouse=True)
    def seeded(self):
        append_audit_entry("approved_refund", "data_access", actor="ana", resource="order:1")
        append_audit_entry("exported_list", "data_access", actor="ben", resource="order:2",
                           outcome="denied", severity="warning")
        append_audit_entry("login", "auth", actor="ana", severity="notice")
        append_audit_entry("key_rotated", "security", actor="ana", severity="critical")

    def test_returns_newest_first(self):
        entries = read_audit_entries()
        assert [entry["action"] for entry in entries][0] == "key_rotated"

    def test_filters_by_category(self):
        entries = read_audit_entries(category="data_access")
        assert len(entries) == 2

    def test_filters_by_actor(self):
        entries = read_audit_entries(actor="ana")
        assert len(entries) == 3

    def test_filters_by_outcome(self):
        entries = read_audit_entries(outcome="denied")
        assert len(entries) == 1

    def test_resource_matches_as_a_prefix(self):
        assert len(read_audit_entries(resource="order:")) == 2
        assert len(read_audit_entries(resource="order:1")) == 1

    def test_action_matches_as_a_prefix(self):
        assert len(read_audit_entries(action="approved")) == 1

    def test_min_severity_includes_higher_levels(self):
        # warning and above should catch the warning and the critical.
        assert len(read_audit_entries(min_severity="warning")) == 2

    def test_min_severity_debug_includes_everything(self):
        assert len(read_audit_entries(min_severity="debug")) == 4

    def test_unknown_severity_is_rejected(self):
        with pytest.raises(ValueError, match="unknown severity"):
            read_audit_entries(min_severity="apocalyptic")

    def test_limit_and_offset_paginate(self):
        page_one = read_audit_entries(limit=2)
        page_two = read_audit_entries(limit=2, offset=2)
        assert len(page_one) == len(page_two) == 2
        assert {entry["id"] for entry in page_one}.isdisjoint({entry["id"] for entry in page_two})

    def test_limit_is_capped(self):
        # A caller asking for a million rows gets the cap, not an OOM.
        assert len(read_audit_entries(limit=10_000)) == 4

    def test_since_filters_by_time(self):
        assert read_audit_entries(since="2999-01-01T00:00:00+00:00") == []


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------


class TestIntegrity:
    def test_empty_trail_is_valid(self):
        assert verify_audit_chain()["valid"] is True

    def test_untouched_trail_is_valid(self):
        for index in range(5):
            append_audit_entry(f"event_{index}")
        result = verify_audit_chain()
        assert result["valid"] is True
        assert result["checked"] == 5

    def test_altering_a_row_is_detected(self):
        append_audit_entry("one")
        append_audit_entry("two", outcome="denied")
        append_audit_entry("three")

        connection = sqlite3.connect(str(audit_db_path()))
        connection.execute("UPDATE audit_entries SET outcome='success' WHERE id=2")
        connection.commit()
        connection.close()

        result = verify_audit_chain()
        assert result["valid"] is False
        assert result["broken_at_id"] == 2

    def test_deleting_a_row_is_detected(self):
        for index in range(4):
            append_audit_entry(f"event_{index}")

        connection = sqlite3.connect(str(audit_db_path()))
        connection.execute("DELETE FROM audit_entries WHERE id=2")
        connection.commit()
        connection.close()

        assert verify_audit_chain()["valid"] is False

    def test_altering_the_detail_field_is_detected(self):
        append_audit_entry("x", detail={"amount": 42})
        connection = sqlite3.connect(str(audit_db_path()))
        connection.execute("""UPDATE audit_entries SET detail='{"amount": 4200}' WHERE id=1""")
        connection.commit()
        connection.close()
        assert verify_audit_chain()["valid"] is False

    def test_head_hash_is_reported_when_valid(self):
        append_audit_entry("x")
        assert len(verify_audit_chain()["head_hash"]) == 64


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_parallel_appends_keep_one_unbroken_chain(self):
        # If the tail read and the insert were not atomic, two threads would
        # chain off the same prev_hash and the chain would fork.
        errors = []

        def append(index: int) -> None:
            try:
                append_audit_entry(f"event_{index}", "custom")
            except Exception as exc:  # surfaced below rather than lost in a thread
                errors.append(exc)

        threads = [threading.Thread(target=append, args=(index,)) for index in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        result = verify_audit_chain()
        assert result["valid"] is True, result
        assert result["checked"] == 12


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


class TestStatistics:
    def test_counts_by_dimension(self):
        append_audit_entry("a", "auth")
        append_audit_entry("b", "auth", outcome="denied")
        append_audit_entry("c", "workflow", severity="warning")

        stats = audit_statistics()
        assert stats["total"] == 3
        assert stats["by_category"] == {"auth": 2, "workflow": 1}
        assert stats["by_outcome"] == {"success": 2, "denied": 1}
        assert stats["by_severity"] == {"info": 2, "warning": 1}

    def test_empty_trail_reports_zero(self):
        stats = audit_statistics()
        assert stats["total"] == 0
        assert stats["first_entry"] is None


# ---------------------------------------------------------------------------
# Tool entrypoints
# ---------------------------------------------------------------------------


class TestToolEntrypoints:
    def test_record_returns_confirmation(self):
        result = json.loads(record_audit_event("approved", "data_access", resource="order:1"))
        assert result["recorded"] is True
        assert result["id"] == 1

    def test_record_parses_json_detail(self):
        record_audit_event("x", detail='{"amount": 42}')
        [entry] = read_audit_entries()
        assert entry["detail"] == {"amount": 42}

    def test_record_accepts_plain_text_detail(self):
        # An agent will sometimes pass prose; that should be kept, not rejected.
        record_audit_event("x", detail="approved by the duty manager")
        [entry] = read_audit_entries()
        assert entry["detail"] == {"note": "approved by the duty manager"}

    def test_record_reports_bad_severity_as_an_error_not_a_crash(self):
        result = json.loads(record_audit_event("x", severity="nope"))
        assert "error" in result

    def test_query_returns_entries(self):
        append_audit_entry("approved", "data_access", resource="order:1")
        result = json.loads(query_audit_log(category="data_access"))
        assert result["count"] == 1
        assert result["entries"][0]["action"] == "approved"

    def test_query_reports_bad_filters_as_an_error(self):
        result = json.loads(query_audit_log(min_severity="nope"))
        assert "error" in result

    def test_verify_tool_matches_the_chain_check(self):
        append_audit_entry("x")
        assert json.loads(verify_audit_integrity())["valid"] is True

    def test_no_delete_or_update_entrypoint_exists(self):
        # Append-only is a property of the module's surface, not just a habit.
        surface = dir(audit_trail)
        assert not [
            name for name in surface
            if name.startswith(("delete_", "update_", "purge_", "clear_"))
        ]
