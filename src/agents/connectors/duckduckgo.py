"""DuckDuckGo search connector for knowledge retrieval."""

from typing import Any

# `duckduckgo_search` was renamed to `ddgs`; the old package no longer returns
# results (DuckDuckGo rate-limits its endpoints). Prefer ddgs, fall back so the
# import never hard-fails.
try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover - legacy fallback
    from duckduckgo_search import DDGS  # type: ignore[assignment]  # same API, older package


class DuckDuckGoConnector:
    """Connector for searching information using DuckDuckGo."""

    def __init__(self, max_results: int = 5) -> None:
        """Initialize the DuckDuckGo connector."""
        self.max_results = max_results

    def search(self, query: str) -> list[dict[str, Any]]:
        """
        Search DuckDuckGo for information.

        Args:
            query: Search query string

        Returns:
            List of search results with title, body, and href
        """
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=self.max_results))
                return results
        except Exception as e:
            print(f"DuckDuckGo search error: {e}")
            return []

    def format_results(self, results: list[dict[str, Any]]) -> str:
        """
        Format search results into a readable string.

        Args:
            results: List of search result dictionaries

        Returns:
            Formatted string with search results
        """
        if not results:
            return "No search results found."

        formatted = []
        for i, result in enumerate(results, 1):
            title = result.get("title", "No title")
            body = result.get("body", "No description")
            href = result.get("href", "")

            formatted.append(f"{i}. {title}\n   {body}\n   Source: {href}")

        return "\n\n".join(formatted)

    def search_and_format(self, query: str) -> str:
        """
        Search and return formatted results in one step.

        Args:
            query: Search query string

        Returns:
            Formatted search results string
        """
        results = self.search(query)
        return self.format_results(results)
