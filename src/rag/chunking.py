"""Split documents into retrievable pieces.

Chunking is the part of a RAG system that decides what an answer can be built
from, so it gets more care than "every N characters". Two rules drive it:

* **Never split mid-thought if a boundary is nearby.** A chunk that begins
  halfway through a sentence retrieves badly, because the embedding is of a
  fragment whose subject appeared in the previous chunk.
* **Overlap.** A fact that straddles a boundary would otherwise be in neither
  chunk in full. The overlap is what makes boundary-straddling facts findable,
  and it is why chunks are allowed to repeat each other's text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

#: Roughly 250-350 words. Large enough to carry an argument, small enough that
#: an embedding still describes one thing rather than averaging three.
DEFAULT_CHUNK_CHARS = 1400
DEFAULT_OVERLAP_CHARS = 220
MIN_CHUNK_CHARS = 80

# Preferred split points, strongest first: a blank line is a real boundary, a
# sentence end is a good one, a line break will do, a space is a last resort.
_BOUNDARIES: tuple[tuple[str, int], ...] = (
    (r"\n\s*\n", 2),
    (r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])", 1),
    (r"\n", 1),
    (r"\s+", 1),
)


@dataclass(slots=True)
class Chunk:
    """One retrievable piece of a document."""

    text: str
    index: int
    start: int
    end: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def characters(self) -> int:
        return len(self.text)


def _normalise(text: str) -> str:
    """Tidy whitespace without destroying paragraph structure."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_point(text: str, target: int, floor: int) -> int:
    """Best place to cut at or before ``target``, never before ``floor``.

    Walks the boundary kinds from strongest to weakest and takes the last match
    that lands in the window. Falling all the way through means the text has no
    whitespace at all — a minified file, a base64 blob — and it is cut squarely,
    because the alternative is one unbounded chunk.
    """
    window = text[:target]
    for pattern, _ in _BOUNDARIES:
        matches = list(re.finditer(pattern, window))
        while matches:
            candidate = matches[-1]
            if candidate.end() >= floor:
                return candidate.end()
            break
    return target


def _resume_point(text: str, ideal: int, look_ahead: int = 90) -> int:
    """Where the next chunk should begin, given where the overlap wants to start.

    Stepping back by the overlap lands on an arbitrary character — usually the
    middle of a word — and a chunk beginning "tection." embeds as nonsense. This
    nudges forward to the nearest real boundary, preferring a sentence start,
    and gives up after ``look_ahead`` characters rather than skipping so far
    ahead that the overlap is lost entirely.
    """
    if ideal <= 0:
        return 0
    window = text[ideal:ideal + look_ahead]
    for pattern in (r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])", r"\n", r"\s+"):
        match = re.search(pattern, window)
        if match:
            return ideal + match.end()
    return ideal


def chunk_text(
    text: str,
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    metadata: dict[str, Any] | None = None,
) -> list[Chunk]:
    """Split ``text`` into overlapping chunks that respect natural boundaries."""
    if chunk_chars < MIN_CHUNK_CHARS:
        raise ValueError(f"chunk_chars must be at least {MIN_CHUNK_CHARS}")
    if not 0 <= overlap_chars < chunk_chars:
        raise ValueError("overlap_chars must be non-negative and smaller than chunk_chars")

    body = _normalise(text)
    if not body:
        return []

    base = dict(metadata or {})
    chunks: list[Chunk] = []
    cursor = 0

    while cursor < len(body):
        remaining = body[cursor:]
        if len(remaining) <= chunk_chars:
            piece, taken = remaining, len(remaining)
        else:
            # Do not accept a boundary so early that the chunk is mostly empty.
            taken = _split_point(remaining, chunk_chars, floor=chunk_chars // 2)
            piece = remaining[:taken]

        stripped = piece.strip()
        if stripped:
            chunks.append(Chunk(
                text=stripped,
                index=len(chunks),
                start=cursor,
                end=cursor + taken,
                metadata=dict(base),
            ))

        if cursor + taken >= len(body):
            break
        # Step back by the overlap, land on a boundary, and always make forward
        # progress however the boundary search turns out.
        resume = _resume_point(body, cursor + max(1, taken - overlap_chars))
        cursor = max(cursor + 1, min(resume, cursor + taken))

    return chunks


def chunk_documents(
    documents: Iterable[tuple[str, dict[str, Any]]],
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    """Chunk several documents, keeping each one's metadata on its pieces."""
    out: list[Chunk] = []
    for text, metadata in documents:
        for chunk in chunk_text(
            text, chunk_chars=chunk_chars, overlap_chars=overlap_chars, metadata=metadata
        ):
            chunk.index = len(out)
            out.append(chunk)
    return out
