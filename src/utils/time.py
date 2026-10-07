"""One rule for time: aware UTC in memory, naive UTC in timezone-less columns.

Values written before the move to aware datetimes, and values read back from
SQLite or ``TIMESTAMP WITHOUT TIME ZONE`` columns, are naive. Comparing one of
those with an aware ``now`` raises ``TypeError``, so everything read from
storage goes through :func:`as_utc` before it is compared or sorted, and
everything written to a timezone-less column goes through :func:`utc_now_naive`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


def utc_now() -> datetime:
    """The current time, aware, in UTC."""
    return datetime.now(UTC)


def utc_now_naive() -> datetime:
    """The current UTC time without tzinfo, for timezone-less database columns.

    PostgreSQL converts an aware value written to a ``timestamp without time
    zone`` column using the session time zone, so a non-UTC server would shift
    every stored time. Naive UTC is stored exactly as given.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def as_utc(value: datetime | None) -> datetime | None:
    """Treat a naive value as UTC; convert an aware one to UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_utc(value: str) -> datetime:
    """``datetime.fromisoformat`` that always returns an aware UTC value."""
    parsed = as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    assert parsed is not None
    return parsed


def _validate_utc(value: datetime) -> datetime:
    result = as_utc(value)
    assert result is not None
    return result


#: A pydantic datetime field that is always aware UTC, whatever it was loaded from.
UTCDateTime = Annotated[datetime, AfterValidator(_validate_utc)]
