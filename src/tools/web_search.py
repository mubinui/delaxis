"""Web search tool using DuckDuckGo."""

from src.agents.connectors.duckduckgo import DuckDuckGoConnector

# Global connector instance
_connector: DuckDuckGoConnector | None = None


def get_connector(max_results: int = 5) -> DuckDuckGoConnector:
    """
    Get or create the DuckDuckGo connector instance.

    Args:
        max_results: Maximum number of search results

    Returns:
        DuckDuckGoConnector instance
    """
    global _connector
    if _connector is None or _connector.max_results != max_results:
        _connector = DuckDuckGoConnector(max_results=max_results)
    return _connector


def search_web(query: str, max_results: int = 5) -> str:
    """
    Search the web using DuckDuckGo and return formatted results.

    This tool performs a web search and returns the top results with
    titles, descriptions, and URLs.

    Args:
        query: Search query string
        max_results: Maximum number of results to return (default: 5)

    Returns:
        Formatted string containing search results with titles, descriptions, and URLs

    Examples:
        >>> results = search_web("Python programming")
        >>> print(results)
        1. Python.org
           Official Python website...
           Source: https://python.org
    """
    connector = get_connector(max_results)
    return connector.search_and_format(query)
