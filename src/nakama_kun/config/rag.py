from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from nakama_kun.config import find_env_file


class RAGSettings(BaseSettings):
    """Configuration settings for nakama_kun's RAG system."""

    model_config = SettingsConfigDict(
        env_file=find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    rag_enabled: bool = Field(
        default=True, validation_alias="RAG_ENABLED"
    )
    rag_db_path: str = Field(
        default=".nakama_rag", validation_alias="RAG_DB_PATH"
    )
    rag_embedding_provider: str = Field(
        default="local", validation_alias="RAG_EMBEDDING_PROVIDER"
    )
    rag_embedding_model: str = Field(
        default="text-embedding-3-small", validation_alias="RAG_EMBEDDING_MODEL"
    )
    rag_embedding_api_key: str | None = Field(
        default=None, validation_alias="RAG_EMBEDDING_API_KEY"
    )
    rag_embedding_base_url: str | None = Field(
        default=None, validation_alias="RAG_EMBEDDING_BASE_URL"
    )
    rag_chunk_size_lines: int = Field(
        default=50, validation_alias="RAG_CHUNK_SIZE_LINES"
    )
    rag_chunk_overlap_lines: int = Field(
        default=10, validation_alias="RAG_CHUNK_OVERLAP_LINES"
    )
