from __future__ import annotations

from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from nakama_kun.config import find_env_file


class TelegramSettings(BaseSettings):
    """Configuration settings for nakama_kun's Telegram interface."""

    model_config = SettingsConfigDict(
        env_file=find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )


    telegram_bot_token: SecretStr | None = Field(
        default=None, validation_alias="TELEGRAM_BOT_TOKEN"
    )
    telegram_allowed_chat_ids: set[int] = Field(
        default_factory=set, validation_alias="TELEGRAM_ALLOWED_CHAT_IDS"
    )

    @field_validator("telegram_allowed_chat_ids", mode="before")
    @classmethod
    def parse_chat_ids(cls, v: Any) -> set[int]:
        """Convert a comma-separated string or list to a set of integers."""
        if not v:
            return set()
        if isinstance(v, (set, list)):
            return {int(x) for x in v}
        if isinstance(v, str):
            # Parse comma-separated string
            return {int(x.strip()) for x in v.split(",") if x.strip()}
        raise ValueError("Invalid format for TELEGRAM_ALLOWED_CHAT_IDS")
