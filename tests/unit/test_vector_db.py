"""Tests for vector database configuration and clients."""

import pytest
from pydantic import ValidationError

from src.config.vector_db_models import (
    ChromaDBConfig,
    PGVectorConfig,
    QdrantConfig,
    VectorDBConfig,
    VectorDBType,
)


class TestVectorDBModels:
    """Tests for vector database configuration models."""

    def test_chromadb_config_defaults(self) -> None:
        """Test ChromaDB configuration with defaults."""
        config = ChromaDBConfig()
        assert config.persist_directory == "./data/chromadb"
        assert config.client_settings is None

    def test_chromadb_config_custom(self) -> None:
        """Test ChromaDB configuration with custom values."""
        config = ChromaDBConfig(
            persist_directory="/custom/path", client_settings={"anonymized_telemetry": False}
        )
        assert config.persist_directory == "/custom/path"
        assert config.client_settings == {"anonymized_telemetry": False}

    def test_pgvector_config_valid(self) -> None:
        """Test PGVector configuration with valid connection string."""
        config = PGVectorConfig(connection_string="postgresql://user:pass@localhost:5432/db")
        assert config.connection_string.startswith("postgresql://")
        assert config.table_name == "embeddings"
        assert config.vector_dimensions == 768

    def test_pgvector_config_invalid_connection_string(self) -> None:
        """Test PGVector configuration with invalid connection string."""
        with pytest.raises(ValidationError, match="Connection string must start"):
            PGVectorConfig(connection_string="invalid://connection")

    def test_qdrant_config_remote(self) -> None:
        """Test Qdrant configuration for remote server."""
        config = QdrantConfig(url="http://localhost:6333", api_key="test_key")
        assert config.url == "http://localhost:6333"
        assert config.api_key == "test_key"
        assert config.prefer_grpc is False
        assert config.timeout == 60

    def test_qdrant_config_local(self) -> None:
        """Test Qdrant configuration for local storage."""
        config = QdrantConfig(path="./data/qdrant")
        assert config.url is None
        assert config.path == "./data/qdrant"

    def test_qdrant_config_invalid_url(self) -> None:
        """Test Qdrant configuration with invalid URL."""
        with pytest.raises(ValidationError, match="URL must start"):
            QdrantConfig(url="invalid-url")

    def test_vector_db_config_chromadb(self) -> None:
        """Test VectorDBConfig for ChromaDB."""
        config = VectorDBConfig(
            type=VectorDBType.CHROMADB,
            collection_name="test_collection",
            embedding_model="all-mpnet-base-v2",
            embedding_dimensions=768,
            distance_metric="cosine",
        )

        # Validate config (should create default ChromaDBConfig)
        config.validate_config()

        assert config.type == VectorDBType.CHROMADB
        assert config.collection_name == "test_collection"
        assert config.chromadb_config is not None
        assert config.chromadb_config.persist_directory == "./data/chromadb"

    def test_vector_db_config_pgvector(self) -> None:
        """Test VectorDBConfig for PGVector."""
        config = VectorDBConfig(
            type=VectorDBType.PGVECTOR,
            collection_name="test_collection",
            embedding_model="all-mpnet-base-v2",
            embedding_dimensions=768,
            distance_metric="cosine",
            pgvector_config=PGVectorConfig(
                connection_string="postgresql://user:pass@localhost:5432/db"
            ),
        )

        config.validate_config()

        assert config.type == VectorDBType.PGVECTOR
        assert config.pgvector_config is not None
        assert config.pgvector_config.connection_string.startswith("postgresql://")

    def test_vector_db_config_pgvector_missing_config(self) -> None:
        """Test VectorDBConfig for PGVector without required config."""
        config = VectorDBConfig(
            type=VectorDBType.PGVECTOR,
            collection_name="test_collection",
            embedding_model="all-mpnet-base-v2",
            embedding_dimensions=768,
            distance_metric="cosine",
        )

        with pytest.raises(ValueError, match="pgvector_config is required"):
            config.validate_config()

    def test_vector_db_config_qdrant(self) -> None:
        """Test VectorDBConfig for Qdrant."""
        config = VectorDBConfig(
            type=VectorDBType.QDRANT,
            collection_name="test_collection",
            embedding_model="all-mpnet-base-v2",
            embedding_dimensions=768,
            distance_metric="cosine",
            qdrant_config=QdrantConfig(url="http://localhost:6333"),
        )

        config.validate_config()

        assert config.type == VectorDBType.QDRANT
        assert config.qdrant_config is not None
        assert config.qdrant_config.url == "http://localhost:6333"

    def test_vector_db_config_invalid_distance_metric(self) -> None:
        """Test VectorDBConfig with invalid distance metric."""
        with pytest.raises(ValidationError, match="Distance metric must be one of"):
            VectorDBConfig(
                type=VectorDBType.CHROMADB,
                collection_name="test_collection",
                embedding_model="all-mpnet-base-v2",
                embedding_dimensions=768,
                distance_metric="invalid_metric",
            )

    def test_vector_db_config_get_connection_string(self) -> None:
        """Test getting connection string from VectorDBConfig."""
        # ChromaDB
        config_chroma = VectorDBConfig(
            type=VectorDBType.CHROMADB,
            collection_name="test",
            embedding_model="all-mpnet-base-v2",
            embedding_dimensions=768,
            chromadb_config=ChromaDBConfig(persist_directory="/custom/path"),
        )
        assert config_chroma.get_connection_string() == "/custom/path"

        # PGVector
        config_pg = VectorDBConfig(
            type=VectorDBType.PGVECTOR,
            collection_name="test",
            embedding_model="all-mpnet-base-v2",
            embedding_dimensions=768,
            pgvector_config=PGVectorConfig(
                connection_string="postgresql://user:pass@localhost:5432/db"
            ),
        )
        assert config_pg.get_connection_string() == "postgresql://user:pass@localhost:5432/db"

        # Qdrant
        config_qdrant = VectorDBConfig(
            type=VectorDBType.QDRANT,
            collection_name="test",
            embedding_model="all-mpnet-base-v2",
            embedding_dimensions=768,
            qdrant_config=QdrantConfig(url="http://localhost:6333"),
        )
        assert config_qdrant.get_connection_string() == "http://localhost:6333"


# Note: local vector DB clients (VectorDBFactory) were removed in favor of the
# external RAG pipeline service (src/tools/rag_pipeline.py). Only the config
# models above remain in use for validating vector database settings.
