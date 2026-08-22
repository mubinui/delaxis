"""What every vector store has to provide.

The interface is deliberately small. Everything above it — chunking, embedding,
ingestion, the tools, the API — is written once against this protocol, so
supporting another database means writing one file and registering it, not
touching the pipeline.

Filtering is expressed as plain equality on metadata rather than as each
backend's own query language. It is the one thing every store can do, it covers
what this system actually needs (restrict to a source, a conversation, a
tenant), and translating a richer language across six backends would be a large
amount of code that nothing calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class VectorStoreError(RuntimeError):
    """A store could not do what was asked, with a reason worth showing."""


@dataclass(slots=True)
class Record:
    """One chunk on its way into a store."""

    id: str
    text: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchHit:
    """One chunk coming back out."""

    id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def source(self) -> str:
        return str(self.metadata.get("source", ""))


@runtime_checkable
class VectorStore(Protocol):
    """The contract every backend implements."""

    name: str

    def upsert(self, collection: str, records: list[Record]) -> int:
        """Add or replace records by id. Returns how many were written."""

    def search(
        self,
        collection: str,
        embedding: list[float],
        top_k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        """Nearest records by cosine similarity, best first."""

    def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
    ) -> int:
        """Remove records by id or by metadata match. Returns how many went."""

    def collections(self) -> list[str]:
        """Every collection this store knows about."""

    def stats(self, collection: str) -> dict[str, Any]:
        """Counts and dimensions for one collection."""

    def sources(self, collection: str) -> list[dict[str, Any]]:
        """The documents in a collection, with chunk counts."""

    def drop(self, collection: str) -> bool:
        """Delete a collection entirely. False if it was not there."""


def cosine(left: list[float], right: list[float]) -> float:
    """Cosine similarity, for stores that do not compute it themselves."""
    if not left or not right:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def matches(metadata: dict[str, Any], where: dict[str, Any] | None) -> bool:
    """Whether a record's metadata satisfies an equality filter."""
    if not where:
        return True
    return all(metadata.get(key) == value for key, value in where.items())
