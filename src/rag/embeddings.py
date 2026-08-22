"""Turning text into vectors.

Three providers, chosen by configuration:

``local``
    Hashed lexical embeddings, computed here, needing no key and no network.
    This is the default, and it is why retrieval works on a fresh checkout with
    nothing configured. It matches on words and word fragments rather than on
    meaning — "car" will not find "automobile" — so it is honest about being a
    good keyword search rather than a poor semantic one.

``openai``
    Any service speaking the OpenAI embeddings API: OpenAI itself, but equally
    OpenRouter, Together, vLLM, LM Studio or Ollama. One implementation covers
    most of what people actually run, local models included, by pointing
    ``base_url`` somewhere else.

``gemini``
    Google's embedding endpoint, which does not speak that API.

Written against httpx rather than an SDK, which is how the rest of this codebase
talks to model providers.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

import httpx
import structlog

logger = structlog.get_logger(__name__)

#: Batch size for remote providers. Large enough to be efficient, small enough
#: to stay under request size limits on long chunks.
BATCH = 64
TIMEOUT = 60.0


class EmbeddingError(RuntimeError):
    """Raised when embeddings cannot be produced, with the reason a human needs."""


class EmbeddingProvider(Protocol):
    """What the rest of the RAG code needs from an embedder."""

    name: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Vectors for documents being stored."""

    def embed_query(self, text: str) -> list[float]:
        """Vector for a search query. Some models want a different prefix."""


# --------------------------------------------------------------------------- #
# Local
# --------------------------------------------------------------------------- #


_WORD = re.compile(r"[a-z0-9]+")


@dataclass
class LocalEmbeddings:
    """Deterministic lexical embeddings, hashed into a fixed number of buckets.

    Words and character trigrams are hashed into ``dimensions`` buckets and
    weighted by sub-linear term frequency, then the vector is normalised so
    cosine similarity behaves. Trigrams are what make it tolerant of plurals,
    tenses and small typos — "deploying" and "deployment" share most of theirs.

    No model, no key, no network, and identical output on every machine, which
    also makes it what the tests use.
    """

    dimensions: int = 512
    name: str = "local"

    #: How much a character trigram counts next to a whole word. Trigrams are
    #: support, not evidence on their own.
    TRIGRAM_WEIGHT = 0.35

    def _vector(self, text: str) -> list[float]:
        # Occurrences and type weight are tracked per token and combined only at
        # the end. Folding them together as they arrive means the sub-linear
        # term below is applied to a fractional count, and 1 + log(0.35) is
        # negative — which silently cancelled every trigram against its own word.
        occurrences: dict[str, int] = {}
        weights: dict[str, float] = {}

        def seen(token: str, weight: float) -> None:
            occurrences[token] = occurrences.get(token, 0) + 1
            weights[token] = weight

        for word in _WORD.findall(text.lower()):
            seen(word, 1.0)
            # Trigrams carry the morphology, so "deploy" still matches
            # "deploys". Padding marks word edges, so "cat" does not look like
            # the middle of "concatenate".
            padded = f" {word} "
            for index in range(len(padded) - 2):
                seen(padded[index:index + 3], self.TRIGRAM_WEIGHT)

        if not occurrences:
            return [0.0] * self.dimensions

        vector = [0.0] * self.dimensions
        for token, count in occurrences.items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest, "big") % self.dimensions
            # Sub-linear: the tenth occurrence of a word says much less than the
            # second, and without this one repeated term dominates the vector.
            vector[bucket] += weights[token] * (1.0 + math.log(count))

        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


# --------------------------------------------------------------------------- #
# Remote
# --------------------------------------------------------------------------- #


@dataclass
class OpenAIEmbeddings:
    """Any service speaking the OpenAI embeddings API."""

    model: str = "text-embedding-3-small"
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    dimensions: int = 1536
    name: str = "openai"

    def _post(self, payload: dict[str, Any]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.base_url.rstrip('/')}/embeddings"
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=TIMEOUT)
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"could not reach the embedding service at {url}: {exc}") from exc

        if response.status_code >= 400:
            raise EmbeddingError(
                f"embedding request failed ({response.status_code}): {response.text[:300]}"
            )
        body = response.json()
        # Order is not promised by the spec, and a shuffled batch silently
        # attaches every vector to the wrong chunk.
        rows = sorted(body.get("data", []), key=lambda row: row.get("index", 0))
        return [row["embedding"] for row in rows]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            batch = [text or " " for text in texts[start:start + BATCH]]
            out.extend(self._post({"model": self.model, "input": batch}))
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


@dataclass
class GeminiEmbeddings:
    """Google's embedding endpoint, which does not speak the OpenAI API."""

    model: str = "text-embedding-004"
    api_key: str | None = None
    dimensions: int = 768
    name: str = "gemini"
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"

    def _embed_one(self, text: str, task: str) -> list[float]:
        url = f"{self.base_url}/models/{self.model}:embedContent?key={self.api_key}"
        payload = {
            "model": f"models/{self.model}",
            "content": {"parts": [{"text": text or " "}]},
            "taskType": task,
        }
        try:
            response = httpx.post(url, json=payload, timeout=TIMEOUT)
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"could not reach Gemini embeddings: {exc}") from exc
        if response.status_code >= 400:
            raise EmbeddingError(
                f"Gemini embedding failed ({response.status_code}): {response.text[:300]}"
            )
        return response.json()["embedding"]["values"]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        # Documents and queries are embedded for different task types; using one
        # for both measurably degrades retrieval on this model family.
        return [self._embed_one(text, "RETRIEVAL_DOCUMENT") for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text, "RETRIEVAL_QUERY")


# --------------------------------------------------------------------------- #


#: Known dimensions, so a store can be created before anything is embedded.
KNOWN_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "text-embedding-004": 768,
    "embedding-001": 768,
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
    "all-minilm": 384,
}

PROVIDERS = ("local", "openai", "gemini")


def create_embedder(
    provider: str = "local",
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    dimensions: int | None = None,
) -> EmbeddingProvider:
    """Build an embedder, falling back to local rather than failing closed.

    A missing key is a configuration problem, not a reason for retrieval to stop
    working: the local provider keeps the feature usable and says loudly in the
    log which one it wanted.
    """
    provider = (provider or "local").strip().lower()

    if provider in ("", "local", "hash", "builtin"):
        return LocalEmbeddings(dimensions=dimensions or 512)

    if provider in ("openai", "openai-compatible", "openrouter", "ollama", "vllm", "lmstudio"):
        key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
        url = base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        chosen = model or "text-embedding-3-small"
        # Local servers do not need a key; hosted ones do.
        if not key and "localhost" not in url and "127.0.0.1" not in url:
            logger.warning("embeddings_no_api_key", provider=provider, falling_back="local")
            return LocalEmbeddings(dimensions=dimensions or 512)
        return OpenAIEmbeddings(
            model=chosen, base_url=url, api_key=key,
            dimensions=dimensions or KNOWN_DIMENSIONS.get(chosen, 1536),
        )

    if provider in ("gemini", "google"):
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            logger.warning("embeddings_no_api_key", provider=provider, falling_back="local")
            return LocalEmbeddings(dimensions=dimensions or 512)
        chosen = model or "text-embedding-004"
        return GeminiEmbeddings(
            model=chosen, api_key=key,
            dimensions=dimensions or KNOWN_DIMENSIONS.get(chosen, 768),
        )

    raise EmbeddingError(
        f"unknown embedding provider {provider!r}; expected one of {', '.join(PROVIDERS)}"
    )
