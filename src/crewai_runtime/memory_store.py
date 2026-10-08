"""Keep CrewAI's memory store compatible with the embedder that queries it.

CrewAI stores crew memory in a LanceDB table under ``CREWAI_STORAGE_DIR``.
The table's vector size is fixed by whichever embedder wrote first. When the
embedder changes (CrewAI's default OpenAI one writes 1536 dimensions, the
local one Delaxis uses writes 512), every recall and every save fails with
"query dim doesn't match the column vector dim", CrewAI logs it, and memory
silently stops working for good.

:func:`retire_mismatched_store` checks the table once per process and, when
its vector size differs from the embedder's, moves it aside (never deletes
it) so CrewAI starts a fresh table of the right size.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

TABLE_DIR = "memories.lance"
_checked: set[str] = set()


def stored_vector_dim(memory_dir: Path) -> int | None:
    """The vector size of the memory table in ``memory_dir``, if one exists."""
    if not (memory_dir / TABLE_DIR).exists():
        return None
    try:
        import lancedb
        import pyarrow as pa

        table = lancedb.connect(str(memory_dir)).open_table("memories")
        field = table.schema.field("vector")
        if pa.types.is_fixed_size_list(field.type):
            return int(field.type.list_size)
    except Exception as exc:  # noqa: BLE001 - an unreadable store is reported, not fatal
        logger.warning("crewai_memory_store_unreadable: %s", exc)
    return None


def retire_mismatched_store(storage_dir: str | Path, dimensions: int) -> Path | None:
    """Move the memory table aside if its vectors are not ``dimensions`` long.

    Returns where it was moved, or None when nothing needed doing. Checked once
    per storage directory per process.
    """
    memory_dir = Path(storage_dir) / "memory"
    key = f"{memory_dir.resolve()}:{dimensions}"
    if key in _checked:
        return None
    _checked.add(key)

    stored = stored_vector_dim(memory_dir)
    if stored is None or stored == dimensions:
        return None

    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    retired = memory_dir / f"{TABLE_DIR}.retired-{stored}d-{stamp}"
    (memory_dir / TABLE_DIR).rename(retired)
    logger.warning(
        "Crew memory was stored with %s-dimension vectors but the embedder produces %s, so "
        "every recall failed. The old store was moved to %s and a new one will be created.",
        stored,
        dimensions,
        retired,
    )
    return retired


def reset_for_tests() -> None:
    _checked.clear()
