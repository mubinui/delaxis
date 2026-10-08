"""Reading JSON whose top level must be an object."""

from __future__ import annotations

from typing import Any


def as_object(value: Any, what: str = "JSON document") -> dict[str, Any]:
    """Return ``value`` as a dict, or raise if the top level is not an object.

    Config files, tool results and HTTP bodies that the code then indexes by
    key must be objects; failing here names the problem instead of failing
    later with an AttributeError on a list or a string.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be a JSON object, got {type(value).__name__}")
    return value
