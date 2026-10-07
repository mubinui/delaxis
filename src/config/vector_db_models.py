"""Pydantic models for vector database configuration validation."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class VectorDBType(StrEnum):
    """Supported vector database types."""

    CHROMADB = "chromadb"
    PGVECTOR = "pgvector"
    QDRANT = "qdrant"
    MONGODB = "mongodb"


class ChromaDBConfig(BaseModel):
    """ChromaDB-specific configuration."""

    persist_directory: str = Field(
        default="./data/chromadb", description="Directory for persistent storage"
    )
    client_settings: dict[str, Any] | None = Field(
        default=None, description="Additional ChromaDB client settings"
    )


class PGVectorConfig(BaseModel):
    """PGVector-specific configuration."""

    connection_string: str = Field(
        description="PostgreSQL connection string (e.g., postgresql://user:pass@host:port/db)"
    )
    table_name: str = Field(default="embeddings", description="Table name for storing vectors")
    vector_dimensions: int = Field(
        default=768, ge=1, description="Dimensionality of embedding vectors"
    )

    @field_validator("connection_string")
    @classmethod
    def validate_connection_string(cls, v: str) -> str:
        """Validate PostgreSQL connection string format."""
        if not v.startswith(("postgresql://", "postgres://")):
            raise ValueError("Connection string must start with 'postgresql://' or 'postgres://'")
        return v


class QdrantConfig(BaseModel):
    """Qdrant-specific configuration."""

    url: str | None = Field(
        default=None,
        description="Qdrant server URL (e.g., http://localhost:6333). None for in-memory.",
    )
    api_key: str | None = Field(default=None, description="API key for Qdrant Cloud")
    prefer_grpc: bool = Field(default=False, description="Use gRPC for communication (faster)")
    timeout: int = Field(default=60, ge=1, description="Request timeout in seconds")
    path: str | None = Field(
        default=None, description="Path for local persistent storage (alternative to url)"
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        """Validate Qdrant URL format."""
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("Qdrant URL must start with 'http://' or 'https://'")
        return v


class MongoDBConfig(BaseModel):
    """MongoDB Atlas-specific configuration."""

    connection_string: str = Field(
        description="MongoDB connection string with vector search enabled"
    )
    database_name: str = Field(description="Database name")
    index_name: str = Field(default="vector_index", description="Name of the vector search index")

    @field_validator("connection_string")
    @classmethod
    def validate_connection_string(cls, v: str) -> str:
        """Validate MongoDB connection string format."""
        if not v.startswith("mongodb"):
            raise ValueError("Connection string must start with 'mongodb://' or 'mongodb+srv://'")
        return v


class VectorDBConfig(BaseModel):
    """Configuration for vector database integration."""

    type: VectorDBType = Field(description="Type of vector database")
    collection_name: str = Field(description="Name of the collection/table for storing vectors")
    embedding_model: str = Field(
        default="all-mpnet-base-v2",
        description="Sentence transformer model for generating embeddings",
    )
    embedding_dimensions: int = Field(
        default=768, ge=1, description="Dimensionality of embedding vectors"
    )
    distance_metric: str = Field(
        default="cosine",
        description="Distance metric for similarity search (cosine, euclidean, dot_product)",
    )

    # Database-specific configurations
    chromadb_config: ChromaDBConfig | None = Field(
        default=None, description="ChromaDB-specific configuration"
    )
    pgvector_config: PGVectorConfig | None = Field(
        default=None, description="PGVector-specific configuration"
    )
    qdrant_config: QdrantConfig | None = Field(
        default=None, description="Qdrant-specific configuration"
    )
    mongodb_config: MongoDBConfig | None = Field(
        default=None, description="MongoDB-specific configuration"
    )

    # Versioning and metadata fields
    version: int = Field(default=1, ge=1, description="Configuration version number")
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of last configuration update",
    )

    @field_validator("distance_metric")
    @classmethod
    def validate_distance_metric(cls, v: str) -> str:
        """Validate distance metric."""
        valid_metrics = {"cosine", "euclidean", "dot_product", "l2", "ip"}
        if v.lower() not in valid_metrics:
            raise ValueError(f"Distance metric must be one of {valid_metrics}")
        return v.lower()

    def validate_config(self) -> None:
        """Validate that the appropriate config is provided for the database type."""
        if self.type == VectorDBType.CHROMADB:
            if self.chromadb_config is None:
                # Provide default config
                self.chromadb_config = ChromaDBConfig()

        elif self.type == VectorDBType.PGVECTOR:
            if self.pgvector_config is None:
                raise ValueError("pgvector_config is required for PGVector database type")

        elif self.type == VectorDBType.QDRANT:
            if self.qdrant_config is None:
                # Provide default config (in-memory)
                self.qdrant_config = QdrantConfig()

        elif self.type == VectorDBType.MONGODB:
            if self.mongodb_config is None:
                raise ValueError("mongodb_config is required for MongoDB database type")

    def get_connection_string(self) -> str | None:
        """Get the connection string for the configured database."""
        if self.type == VectorDBType.PGVECTOR and self.pgvector_config:
            return self.pgvector_config.connection_string
        elif self.type == VectorDBType.QDRANT and self.qdrant_config:
            return self.qdrant_config.url
        elif self.type == VectorDBType.MONGODB and self.mongodb_config:
            return self.mongodb_config.connection_string
        elif self.type == VectorDBType.CHROMADB and self.chromadb_config:
            return self.chromadb_config.persist_directory
        return None


class VectorDBRegistry(BaseModel):
    """Registry for managing multiple vector database configurations."""

    version: str = Field(default="1.0", description="Configuration version")
    databases: list[VectorDBConfig] = Field(
        default_factory=list, description="List of vector database configurations"
    )

    def get_database(self, collection_name: str) -> VectorDBConfig | None:
        """Get vector database configuration by collection name."""
        return next((db for db in self.databases if db.collection_name == collection_name), None)

    def validate_all(self) -> None:
        """Validate all database configurations."""
        for db in self.databases:
            db.validate_config()
