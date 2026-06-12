from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MemorySettings(BaseSettings):
    """Configuration settings for nakama_kun's memory system."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    memory_enabled: bool = Field(
        default=True, validation_alias="MEMORY_ENABLED"
    )
    memory_db_path: str = Field(
        default="nakama_memory.db", validation_alias="MEMORY_DB_PATH"
    )
