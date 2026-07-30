"""Environment-variable lookup with a deprecated ``OAK_*`` fallback.

The product was renamed from Open Agent Kit to Delaxis, and its environment
variables moved from the ``OAK_`` prefix to ``DELAXIS_``. A deployment that
still exports the old names would otherwise fall back to defaults silently —
serving the wrong static directory, or writing data somewhere new — so the old
names keep working and log a one-time warning instead.

Remove this module (and its call sites) in 0.6.0.
"""

from __future__ import annotations

import os

import structlog

logger = structlog.get_logger(__name__)

_LEGACY_PREFIX = "OAK_"
_PREFIX = "DELAXIS_"

# One warning per variable, not one per read — these are read on every request
# in some call sites.
_warned: set[str] = set()


def _warn_once(legacy: str, current: str) -> None:
    if legacy in _warned:
        return
    _warned.add(legacy)
    logger.warning(
        "deprecated_env_var",
        legacy=legacy,
        replacement=current,
        detail=f"{legacy} is deprecated and will be removed in 0.6.0; rename it to {current}",
    )


def env(name: str, default: str | None = None) -> str | None:
    """Read ``DELAXIS_*``, falling back to the pre-rename ``OAK_*`` spelling.

    ``name`` must be the new (``DELAXIS_``-prefixed) name. An empty string is a
    real value and is returned as-is; only an unset variable falls through.
    """
    value = os.environ.get(name)
    if value is not None:
        return value

    if name.startswith(_PREFIX):
        legacy = _LEGACY_PREFIX + name[len(_PREFIX):]
        value = os.environ.get(legacy)
        if value is not None:
            _warn_once(legacy, name)
            return value

    return default


def reset_warnings() -> None:
    """Forget which variables have been warned about (tests only)."""
    _warned.clear()
