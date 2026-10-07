"""Unit tests for ProviderAdapter."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from src.infrastructure.providers.adapter import ProviderAdapter, get_provider_adapter


@pytest.fixture
def temp_config_files(tmp_path):
    """Create temporary configuration files."""
    config_dir = tmp_path / "configs"
    config_dir.mkdir()

    # API providers config
    providers_data = {
        "providers": [
            {
                "id": "test_llm",
                "name": "Test LLM",
                "type": "llm",
                "base_url": "https://api.test.com",
                "enabled": True,
                "auth": {"scheme": "bearer", "env_var": "TEST_API_KEY"},
            },
            {
                "id": "test_api",
                "name": "Test API",
                "type": "api",
                "base_url": "https://api.example.com",
                "enabled": True,
                "auth": {
                    "scheme": "api_key",
                    "header_name": "X-API-Key",
                    "env_var": "EXAMPLE_API_KEY",
                },
            },
            {
                "id": "disabled_provider",
                "name": "Disabled Provider",
                "type": "llm",
                "base_url": "https://disabled.com",
                "enabled": False,
            },
        ]
    }

    # Vector DB config
    vector_db_data = {
        "databases": [
            {
                "type": "chromadb",
                "collection_name": "test_collection",
                "embedding_model": "all-mpnet-base-v2",
                "chromadb_config": {"persist_directory": "/tmp/chromadb"},
            },
            {
                "type": "qdrant",
                "collection_name": "qdrant_collection",
                "embedding_model": "all-mpnet-base-v2",
                "qdrant_config": {"url": "http://localhost:6333", "api_key": "{{QDRANT_API_KEY}}"},
            },
        ]
    }

    providers_file = config_dir / "api_providers.json"
    vector_db_file = config_dir / "vector_databases.json"

    providers_file.write_text(json.dumps(providers_data))
    vector_db_file.write_text(json.dumps(vector_db_data))

    return {
        "config_dir": config_dir,
        "providers_file": providers_file,
        "vector_db_file": vector_db_file,
    }


def test_provider_adapter_initialization(temp_config_files):
    """Test ProviderAdapter initialization."""
    adapter = ProviderAdapter(
        config_path=str(temp_config_files["providers_file"]),
        vector_db_config_path=str(temp_config_files["vector_db_file"]),
        enable_file_watching=False,
    )

    assert adapter is not None
    assert len(adapter._providers) == 3


def test_get_llm_client_success(temp_config_files):
    """Test successfully getting an LLM client."""
    with patch.dict("os.environ", {"TEST_API_KEY": "test_key_123"}):
        with patch("src.infrastructure.providers.adapter.httpx.AsyncClient") as mock_client:
            adapter = ProviderAdapter(
                config_path=str(temp_config_files["providers_file"]),
                vector_db_config_path=str(temp_config_files["vector_db_file"]),
                enable_file_watching=False,
            )

            client = adapter.get_llm_client("test_llm")

            assert client is not None
            mock_client.assert_called_once()
            # Verify authorization header was set
            call_kwargs = mock_client.call_args[1]
            assert "headers" in call_kwargs
            assert "Authorization" in call_kwargs["headers"]
            assert call_kwargs["headers"]["Authorization"] == "Bearer test_key_123"


def test_get_llm_client_not_found(temp_config_files):
    """Test getting a non-existent LLM client."""
    adapter = ProviderAdapter(
        config_path=str(temp_config_files["providers_file"]),
        vector_db_config_path=str(temp_config_files["vector_db_file"]),
        enable_file_watching=False,
    )

    with pytest.raises(ValueError, match="Provider not found"):
        adapter.get_llm_client("nonexistent")


def test_get_llm_client_disabled(temp_config_files):
    """Test getting a disabled LLM client."""
    adapter = ProviderAdapter(
        config_path=str(temp_config_files["providers_file"]),
        vector_db_config_path=str(temp_config_files["vector_db_file"]),
        enable_file_watching=False,
    )

    with pytest.raises(ValueError, match="Provider disabled"):
        adapter.get_llm_client("disabled_provider")


def test_get_llm_client_wrong_type(temp_config_files):
    """Test getting LLM client for non-LLM provider."""
    adapter = ProviderAdapter(
        config_path=str(temp_config_files["providers_file"]),
        vector_db_config_path=str(temp_config_files["vector_db_file"]),
        enable_file_watching=False,
    )

    with pytest.raises(ValueError, match="not an LLM provider"):
        adapter.get_llm_client("test_api")


def test_get_llm_client_caching(temp_config_files):
    """Test that LLM clients are cached."""
    with patch.dict("os.environ", {"TEST_API_KEY": "test_key_123"}):
        with patch("src.infrastructure.providers.adapter.httpx.AsyncClient") as mock_client:
            adapter = ProviderAdapter(
                config_path=str(temp_config_files["providers_file"]),
                vector_db_config_path=str(temp_config_files["vector_db_file"]),
                cache_ttl_seconds=300,
                enable_file_watching=False,
            )

            # First call
            client1 = adapter.get_llm_client("test_llm")
            # Second call (should use cache)
            client2 = adapter.get_llm_client("test_llm")

            # Should only create client once
            assert mock_client.call_count == 1
            assert client1 is client2


def test_get_api_client_success(temp_config_files):
    """Test successfully getting an API client."""
    with patch.dict("os.environ", {"EXAMPLE_API_KEY": "api_key_456"}):
        with patch("src.infrastructure.providers.adapter.httpx.AsyncClient") as mock_client:
            adapter = ProviderAdapter(
                config_path=str(temp_config_files["providers_file"]),
                vector_db_config_path=str(temp_config_files["vector_db_file"]),
                enable_file_watching=False,
            )

            client = adapter.get_api_client("test_api")

            assert client is not None
            mock_client.assert_called_once()
            # Verify API key header was set
            call_kwargs = mock_client.call_args[1]
            assert "headers" in call_kwargs
            assert "X-API-Key" in call_kwargs["headers"]
            assert call_kwargs["headers"]["X-API-Key"] == "api_key_456"


def test_get_vector_db_client_removed(temp_config_files):
    """Local vector DB clients were removed in favor of the external RAG service."""
    adapter = ProviderAdapter(
        config_path=str(temp_config_files["providers_file"]),
        vector_db_config_path=str(temp_config_files["vector_db_file"]),
        enable_file_watching=False,
    )

    with pytest.raises(NotImplementedError, match="RAG pipeline"):
        adapter.get_vector_db_client("test_collection")


def test_get_credentials_from_env(temp_config_files):
    """Test retrieving credentials from environment variables."""
    with patch.dict("os.environ", {"TEST_CREDENTIAL": "secret_value"}):
        adapter = ProviderAdapter(
            config_path=str(temp_config_files["providers_file"]),
            vector_db_config_path=str(temp_config_files["vector_db_file"]),
            enable_file_watching=False,
        )

        credential = adapter.get_credentials("test_provider", "TEST_CREDENTIAL")

        assert credential == "secret_value"


def test_get_credentials_not_found(temp_config_files):
    """Test retrieving non-existent credentials."""
    adapter = ProviderAdapter(
        config_path=str(temp_config_files["providers_file"]),
        vector_db_config_path=str(temp_config_files["vector_db_file"]),
        enable_file_watching=False,
    )

    credential = adapter.get_credentials("test_provider", "NONEXISTENT_KEY")

    assert credential is None


def test_reload_configs(temp_config_files):
    """Test hot reloading configurations."""
    adapter = ProviderAdapter(
        config_path=str(temp_config_files["providers_file"]),
        vector_db_config_path=str(temp_config_files["vector_db_file"]),
        enable_file_watching=False,
    )

    # Cache a client
    with patch.dict("os.environ", {"TEST_API_KEY": "test_key_123"}):
        with patch("src.infrastructure.providers.adapter.httpx.AsyncClient"):
            adapter.get_llm_client("test_llm")
            assert len(adapter._llm_clients) == 1

    # Reload configs
    adapter.reload_configs()

    # Cache should be cleared
    assert len(adapter._llm_clients) == 0
    assert len(adapter._vector_db_clients) == 0
    assert len(adapter._search_clients) == 0
    assert len(adapter._api_clients) == 0


def test_reload_configs_updates_providers(temp_config_files):
    """Test that reload_configs updates provider configurations."""
    adapter = ProviderAdapter(
        config_path=str(temp_config_files["providers_file"]),
        vector_db_config_path=str(temp_config_files["vector_db_file"]),
        enable_file_watching=False,
    )

    len(adapter._providers)

    # Update config file
    new_providers_data = {
        "providers": [
            {
                "id": "new_provider",
                "name": "New Provider",
                "type": "llm",
                "base_url": "https://new.com",
                "enabled": True,
            }
        ]
    }
    temp_config_files["providers_file"].write_text(json.dumps(new_providers_data))

    # Reload
    adapter.reload_configs()

    # Should have new provider
    assert len(adapter._providers) == 1
    assert "new_provider" in adapter._providers


def test_cache_expiration(temp_config_files):
    """Test that cached clients expire after TTL."""
    with patch.dict("os.environ", {"TEST_API_KEY": "test_key_123"}):
        with patch("src.infrastructure.providers.adapter.httpx.AsyncClient") as mock_client:
            adapter = ProviderAdapter(
                config_path=str(temp_config_files["providers_file"]),
                vector_db_config_path=str(temp_config_files["vector_db_file"]),
                cache_ttl_seconds=1,  # 1 second TTL
                enable_file_watching=False,
            )

            # First call
            adapter.get_llm_client("test_llm")
            assert mock_client.call_count == 1

            # Manually expire the cache by modifying the timestamp
            provider_id = "test_llm"
            if provider_id in adapter._llm_clients:
                client, _ = adapter._llm_clients[provider_id]
                # Set timestamp to past
                adapter._llm_clients[provider_id] = (
                    client,
                    datetime.now(UTC) - timedelta(seconds=10),
                )

            # Second call (cache expired, should create new client)
            adapter.get_llm_client("test_llm")

            # Should create client twice
            assert mock_client.call_count == 2


def test_file_watcher_start_stop(temp_config_files):
    """Test starting and stopping file watcher."""
    adapter = ProviderAdapter(
        config_path=str(temp_config_files["providers_file"]),
        vector_db_config_path=str(temp_config_files["vector_db_file"]),
        enable_file_watching=False,
    )

    # Start watcher
    adapter.start_file_watcher()
    assert adapter._watcher_thread is not None
    assert adapter._watcher_thread.is_alive()

    # Stop watcher
    adapter.stop_file_watcher()
    assert not adapter._watcher_thread.is_alive()


def test_file_watcher_already_running(temp_config_files):
    """Test starting file watcher when already running."""
    adapter = ProviderAdapter(
        config_path=str(temp_config_files["providers_file"]),
        vector_db_config_path=str(temp_config_files["vector_db_file"]),
        enable_file_watching=False,
    )

    # Start watcher
    adapter.start_file_watcher()
    thread1 = adapter._watcher_thread

    # Try to start again
    adapter.start_file_watcher()
    thread2 = adapter._watcher_thread

    # Should be same thread
    assert thread1 is thread2

    # Cleanup
    adapter.stop_file_watcher()


def test_file_watcher_not_running(temp_config_files):
    """Test stopping file watcher when not running."""
    adapter = ProviderAdapter(
        config_path=str(temp_config_files["providers_file"]),
        vector_db_config_path=str(temp_config_files["vector_db_file"]),
        enable_file_watching=False,
    )

    # Try to stop when not running (should not raise error)
    adapter.stop_file_watcher()


def test_get_provider_adapter_singleton():
    """Test that get_provider_adapter returns singleton."""
    # Reset singleton
    import src.infrastructure.providers.adapter as adapter_module

    adapter_module._provider_adapter = None

    with patch("src.infrastructure.providers.adapter.ProviderAdapter") as mock_adapter:
        adapter1 = get_provider_adapter()
        adapter2 = get_provider_adapter()

        # Should only create once
        assert mock_adapter.call_count == 1
        assert adapter1 is adapter2


def test_missing_config_files():
    """Test handling missing configuration files."""
    adapter = ProviderAdapter(
        config_path="/nonexistent/providers.json",
        vector_db_config_path="/nonexistent/vector_db.json",
        enable_file_watching=False,
    )

    # Should initialize with empty configs
    assert len(adapter._providers) == 0


def test_create_llm_client_without_credentials(temp_config_files):
    """Test creating LLM client when credentials are not available."""
    # Don't set environment variable
    with patch("src.infrastructure.providers.adapter.httpx.AsyncClient") as mock_client:
        adapter = ProviderAdapter(
            config_path=str(temp_config_files["providers_file"]),
            vector_db_config_path=str(temp_config_files["vector_db_file"]),
            enable_file_watching=False,
        )

        # Should still create client but without auth header
        client = adapter.get_llm_client("test_llm")

        assert client is not None
        mock_client.assert_called_once()


def test_create_api_client_basic_auth(temp_config_files):
    """Test creating API client with basic authentication."""
    # Add basic auth provider to config
    providers_data = {
        "providers": [
            {
                "id": "basic_auth_api",
                "name": "Basic Auth API",
                "type": "api",
                "base_url": "https://api.basic.com",
                "enabled": True,
                "auth": {"scheme": "basic", "env_var": "BASIC_AUTH_CREDS"},
            }
        ]
    }
    temp_config_files["providers_file"].write_text(json.dumps(providers_data))

    with patch.dict("os.environ", {"BASIC_AUTH_CREDS": "user:password"}):
        with patch("src.infrastructure.providers.adapter.httpx.AsyncClient") as mock_client:
            adapter = ProviderAdapter(
                config_path=str(temp_config_files["providers_file"]),
                vector_db_config_path=str(temp_config_files["vector_db_file"]),
                enable_file_watching=False,
            )

            client = adapter.get_api_client("basic_auth_api")

            assert client is not None
            mock_client.assert_called_once()
            # Verify basic auth header was set
            call_kwargs = mock_client.call_args[1]
            assert "headers" in call_kwargs
            assert "Authorization" in call_kwargs["headers"]
            assert call_kwargs["headers"]["Authorization"].startswith("Basic ")
