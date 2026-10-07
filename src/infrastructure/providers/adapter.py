"""Unified provider adapter for managing all external service clients."""

import asyncio
import json
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog

from src.config.dynamic_models import AuthScheme, ProviderConfig, ProviderType
from src.infrastructure.secrets import get_global_credential_manager
from src.observability.metrics import (
    config_reload_total,
    provider_client_created_total,
)

logger = structlog.get_logger(__name__)


class ProviderAdapter:
    """
    Unified adapter for instantiating and managing all external service clients.

    This adapter provides a single interface for:
    - LLM clients (OpenRouter, OpenAI, etc.)
    - Vector database clients (ChromaDB, PGVector, Qdrant, MongoDB)
    - Search clients (DuckDuckGo, etc.)
    - API clients (custom integrations)

    Features:
    - Credential retrieval from environment variables or secret management systems
    - Client caching with TTL
    - Hot reload of configurations
    - Metrics emission for observability
    """

    def __init__(
        self,
        config_path: str = "configs/api_providers.json",
        vector_db_config_path: str = "configs/vector_databases.json",
        cache_ttl_seconds: int = 300,
        enable_file_watching: bool = False,
        watch_interval_seconds: int = 5,
    ) -> None:
        """
        Initialize the provider adapter.

        Args:
            config_path: Path to API providers configuration file
            vector_db_config_path: Path to vector databases configuration file
            cache_ttl_seconds: TTL for cached clients (default: 5 minutes)
            enable_file_watching: Enable automatic file watching for hot reload
            watch_interval_seconds: Interval for checking file changes (default: 5 seconds)
        """
        self.config_path = Path(config_path)
        self.vector_db_config_path = Path(vector_db_config_path)
        self.cache_ttl_seconds = cache_ttl_seconds
        self.enable_file_watching = enable_file_watching
        self.watch_interval_seconds = watch_interval_seconds

        # Client caches with TTL
        self._llm_clients: dict[str, tuple[Any, datetime]] = {}
        self._vector_db_clients: dict[str, tuple[Any, datetime]] = {}
        self._search_clients: dict[str, tuple[Any, datetime]] = {}
        self._api_clients: dict[str, tuple[Any, datetime]] = {}

        # Configuration caches
        self._providers: dict[str, ProviderConfig] = {}

        # Credential manager
        self._credential_manager = get_global_credential_manager()

        # File watching
        self._file_mtimes: dict[Path, float] = {}
        self._watcher_thread: threading.Thread | None = None
        self._stop_watching = threading.Event()

        # Load initial configurations
        self._load_configurations()

        # Start file watcher if enabled
        if self.enable_file_watching:
            self.start_file_watcher()

        logger.info(
            "provider_adapter_initialized",
            config_path=str(self.config_path),
            vector_db_config_path=str(self.vector_db_config_path),
            cache_ttl_seconds=cache_ttl_seconds,
            file_watching_enabled=enable_file_watching,
        )

    def get_llm_client(self, provider_id: str) -> httpx.AsyncClient:
        """
        Get or create an LLM client instance.

        Args:
            provider_id: Provider identifier

        Returns:
            Configured HTTP client for LLM API

        Raises:
            ValueError: If provider not found or disabled
        """
        # Check cache
        if provider_id in self._llm_clients:
            client, cached_at = self._llm_clients[provider_id]
            if datetime.now(UTC) - cached_at < timedelta(seconds=self.cache_ttl_seconds):
                logger.debug("llm_client_cache_hit", provider_id=provider_id)
                return client

        # Get provider configuration
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ValueError(f"Provider not found: {provider_id}")

        if not provider.enabled:
            raise ValueError(f"Provider disabled: {provider_id}")

        if provider.type != ProviderType.LLM:
            raise ValueError(
                f"Provider {provider_id} is not an LLM provider (type: {provider.type})"
            )

        # Create new client
        client = self._create_llm_client(provider)

        # Cache the client
        self._llm_clients[provider_id] = (client, datetime.now(UTC))

        # Emit metrics
        provider_client_created_total.labels(provider_id=provider_id, client_type="llm").inc()

        logger.info("llm_client_created", provider_id=provider_id)
        return client

    def get_vector_db_client(self, db_id: str) -> Any:
        """
        Get or create a vector database client instance.

        Note: Vector DB support (chromadb, pgvector, qdrant) has been removed.
        Use the external RAG pipeline service instead.

        Args:
            db_id: Database identifier (collection name)

        Raises:
            NotImplementedError: Always, as vector DB clients are no longer supported
        """
        raise NotImplementedError(
            "Local vector DB clients have been removed. "
            "Use the external RAG pipeline service via src.tools.rag_pipeline instead."
        )

    def get_search_client(self, provider_id: str) -> Any:
        """
        Get or create a search client instance.

        Args:
            provider_id: Provider identifier

        Returns:
            Search client instance

        Raises:
            ValueError: If provider not found or disabled
        """
        # Check cache
        if provider_id in self._search_clients:
            client, cached_at = self._search_clients[provider_id]
            if datetime.now(UTC) - cached_at < timedelta(seconds=self.cache_ttl_seconds):
                logger.debug("search_client_cache_hit", provider_id=provider_id)
                return client

        # Get provider configuration
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ValueError(f"Provider not found: {provider_id}")

        if not provider.enabled:
            raise ValueError(f"Provider disabled: {provider_id}")

        if provider.type != ProviderType.TOOL:
            raise ValueError(
                f"Provider {provider_id} is not a tool provider (type: {provider.type})"
            )

        # Create new client
        client = self._create_search_client(provider)

        # Cache the client
        self._search_clients[provider_id] = (client, datetime.now(UTC))

        # Emit metrics
        provider_client_created_total.labels(provider_id=provider_id, client_type="search").inc()

        logger.info("search_client_created", provider_id=provider_id)
        return client

    def get_api_client(self, provider_id: str) -> httpx.AsyncClient:
        """
        Get or create a generic API client instance.

        Args:
            provider_id: Provider identifier

        Returns:
            Configured HTTP client

        Raises:
            ValueError: If provider not found or disabled
        """
        # Check cache
        if provider_id in self._api_clients:
            client, cached_at = self._api_clients[provider_id]
            if datetime.now(UTC) - cached_at < timedelta(seconds=self.cache_ttl_seconds):
                logger.debug("api_client_cache_hit", provider_id=provider_id)
                return client

        # Get provider configuration
        provider = self._providers.get(provider_id)
        if provider is None:
            raise ValueError(f"Provider not found: {provider_id}")

        if not provider.enabled:
            raise ValueError(f"Provider disabled: {provider_id}")

        if provider.type != ProviderType.API:
            raise ValueError(
                f"Provider {provider_id} is not an API provider (type: {provider.type})"
            )

        # Create new client
        client = self._create_api_client(provider)

        # Cache the client
        self._api_clients[provider_id] = (client, datetime.now(UTC))

        # Emit metrics
        provider_client_created_total.labels(provider_id=provider_id, client_type="api").inc()

        logger.info("api_client_created", provider_id=provider_id)
        return client

    def get_credentials(self, provider_id: str, credential_key: str) -> str | None:
        """
        Retrieve credentials from environment or secret management system.

        This method:
        1. Checks environment variables first
        2. Falls back to secret management system if configured
        3. Never logs or exposes the actual credential value

        Args:
            provider_id: Provider identifier (for logging)
            credential_key: Environment variable or secret name

        Returns:
            Credential value or None if not found
        """
        # Try environment variable first
        credential = os.getenv(credential_key)
        if credential:
            logger.debug(
                "credential_retrieved_from_env",
                provider_id=provider_id,
                credential_key=credential_key,
            )
            return credential

        # Try secret management system
        try:
            credential = asyncio.run(
                self._credential_manager.retrieve_credential(credential_key, encrypted=True)
            )
            if credential:
                logger.debug(
                    "credential_retrieved_from_secret_manager",
                    provider_id=provider_id,
                    credential_key=credential_key,
                )
                return credential
        except Exception as e:
            logger.warning(
                "credential_retrieval_from_secret_manager_failed",
                provider_id=provider_id,
                credential_key=credential_key,
                error=str(e),
            )

        logger.warning(
            "credential_not_found",
            provider_id=provider_id,
            credential_key=credential_key,
        )
        return None

    def reload_configs(self) -> None:
        """
        Hot reload all configurations without service restart.

        This method:
        1. Reloads configuration files from disk
        2. Invalidates all client caches
        3. Emits metrics for reload events
        """
        logger.info("reloading_provider_configurations")

        try:
            # Clear all caches
            self._llm_clients.clear()
            self._vector_db_clients.clear()
            self._search_clients.clear()
            self._api_clients.clear()

            # Reload configurations
            self._load_configurations()

            # Emit metrics
            config_reload_total.labels(config_type="providers").inc()

            logger.info(
                "provider_configurations_reloaded",
                providers_count=len(self._providers),
            )

        except Exception as e:
            logger.error("provider_configuration_reload_failed", error=str(e))
            raise

    def _load_configurations(self) -> None:
        """Load configurations from JSON files."""
        # Drop providers removed from the config file since the last load
        self._providers.clear()

        # Load API providers
        if self.config_path.exists():
            with open(self.config_path) as f:
                data = json.load(f)
                for provider_data in data.get("providers", []):
                    try:
                        provider = ProviderConfig(**provider_data)
                        self._providers[provider.id] = provider
                    except Exception as e:
                        logger.error(
                            "failed_to_load_provider",
                            provider_id=provider_data.get("id"),
                            error=str(e),
                        )
        else:
            logger.warning("provider_config_file_not_found", path=str(self.config_path))

    def _create_llm_client(self, provider: ProviderConfig) -> httpx.AsyncClient:
        """
        Create an HTTP client for LLM provider.

        Args:
            provider: Provider configuration

        Returns:
            Configured HTTP client
        """
        headers = {}

        # Add authentication
        if provider.auth:
            credential = None
            if provider.auth.env_var:
                credential = self.get_credentials(provider.id, provider.auth.env_var)

            if credential:
                if provider.auth.scheme == AuthScheme.BEARER:
                    headers["Authorization"] = f"Bearer {credential}"
                elif provider.auth.scheme == AuthScheme.API_KEY:
                    if provider.auth.header_name:
                        headers[provider.auth.header_name] = credential
            else:
                logger.warning(
                    "llm_provider_credential_not_found",
                    provider_id=provider.id,
                    env_var=provider.auth.env_var,
                )

        # Add default headers
        if provider.request_defaults and provider.request_defaults.headers:
            headers.update(provider.request_defaults.headers)

        # Create client
        timeout = provider.request_defaults.timeout_seconds if provider.request_defaults else 120

        return httpx.AsyncClient(
            base_url=provider.base_url,
            headers=headers,
            timeout=timeout,
        )

    def _create_search_client(self, provider: ProviderConfig) -> Any:
        """
        Create a search client by importing from entrypoint.

        Args:
            provider: Provider configuration

        Returns:
            Search client instance
        """
        if not provider.entrypoint:
            return provider

        try:
            # Parse entrypoint like "src.agents.connectors.duckduckgo:DuckDuckGoConnector"
            module_path, class_name = provider.entrypoint.split(":")
            module = __import__(module_path, fromlist=[class_name])
            cls = getattr(module, class_name)

            # Instantiate with settings
            return cls(**provider.settings)

        except Exception as e:
            logger.error(
                "failed_to_create_search_client",
                provider_id=provider.id,
                error=str(e),
            )
            raise ValueError(f"Failed to create search client for {provider.id}: {e}") from e

    def _create_api_client(self, provider: ProviderConfig) -> httpx.AsyncClient:
        """
        Create a generic API client.

        Args:
            provider: Provider configuration

        Returns:
            Configured HTTP client
        """
        headers = {}

        # Add authentication
        if provider.auth:
            credential = None
            if provider.auth.env_var:
                credential = self.get_credentials(provider.id, provider.auth.env_var)

            if credential:
                if provider.auth.scheme == AuthScheme.BEARER:
                    headers["Authorization"] = f"Bearer {credential}"
                elif provider.auth.scheme == AuthScheme.API_KEY:
                    if provider.auth.header_name:
                        headers[provider.auth.header_name] = credential
                elif provider.auth.scheme == AuthScheme.BASIC:
                    # For basic auth, credential should be "username:password"
                    import base64

                    encoded = base64.b64encode(credential.encode()).decode()
                    headers["Authorization"] = f"Basic {encoded}"
            else:
                logger.warning(
                    "api_provider_credential_not_found",
                    provider_id=provider.id,
                    env_var=provider.auth.env_var,
                )

        # Add default headers
        if provider.request_defaults and provider.request_defaults.headers:
            headers.update(provider.request_defaults.headers)

        # Create client
        timeout = provider.request_defaults.timeout_seconds if provider.request_defaults else 30

        return httpx.AsyncClient(
            base_url=provider.base_url,
            headers=headers,
            timeout=timeout,
        )

    def start_file_watcher(self) -> None:
        """
        Start watching configuration files for changes.

        This method starts a background thread that periodically checks
        for file modifications and triggers automatic reload.
        """
        if self._watcher_thread is not None and self._watcher_thread.is_alive():
            logger.warning("file_watcher_already_running")
            return

        # Record initial modification times
        self._update_file_mtimes()

        # Start watcher thread
        self._stop_watching.clear()
        self._watcher_thread = threading.Thread(
            target=self._watch_files, daemon=True, name="ProviderAdapterFileWatcher"
        )
        self._watcher_thread.start()

        logger.info(
            "file_watcher_started",
            watch_interval_seconds=self.watch_interval_seconds,
        )

    def stop_file_watcher(self) -> None:
        """Stop watching configuration files."""
        if self._watcher_thread is None or not self._watcher_thread.is_alive():
            logger.warning("file_watcher_not_running")
            return

        self._stop_watching.set()
        self._watcher_thread.join(timeout=5)

        logger.info("file_watcher_stopped")

    def _watch_files(self) -> None:
        """Background thread function for watching configuration files."""
        while not self._stop_watching.is_set():
            try:
                # Check for file changes
                if self._check_file_changes():
                    logger.info("configuration_files_changed_reloading")
                    self.reload_configs()

                # Sleep for the watch interval
                self._stop_watching.wait(self.watch_interval_seconds)

            except Exception as e:
                logger.error("file_watcher_error", error=str(e))
                # Continue watching despite errors
                self._stop_watching.wait(self.watch_interval_seconds)

    def _check_file_changes(self) -> bool:
        """
        Check if any configuration files have been modified.

        Returns:
            True if any files have changed, False otherwise
        """
        changed = False

        for file_path in [self.config_path, self.vector_db_config_path]:
            if not file_path.exists():
                continue

            current_mtime = file_path.stat().st_mtime
            previous_mtime = self._file_mtimes.get(file_path)

            if previous_mtime is not None and current_mtime > previous_mtime:
                logger.info(
                    "configuration_file_modified",
                    file_path=str(file_path),
                    previous_mtime=previous_mtime,
                    current_mtime=current_mtime,
                )
                changed = True

        if changed:
            self._update_file_mtimes()

        return changed

    def _update_file_mtimes(self) -> None:
        """Update the recorded modification times for configuration files."""
        for file_path in [self.config_path, self.vector_db_config_path]:
            if file_path.exists():
                self._file_mtimes[file_path] = file_path.stat().st_mtime


# Singleton instance
_provider_adapter: ProviderAdapter | None = None


def get_provider_adapter() -> ProviderAdapter:
    """
    Get the singleton provider adapter instance.

    Returns:
        ProviderAdapter instance
    """
    global _provider_adapter
    if _provider_adapter is None:
        _provider_adapter = ProviderAdapter()
        logger.info("provider_adapter_singleton_initialized")
    return _provider_adapter
