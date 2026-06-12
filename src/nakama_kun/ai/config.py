from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from nakama_kun.config import find_env_file


class AISettings(BaseSettings):
    """Configuration system for nakama_kun's AI layer."""

    model_config = SettingsConfigDict(
        env_file=find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )


    openrouter_api_key: SecretStr | None = Field(
        default=None, validation_alias="OPENROUTER_API_KEY"
    )
    openrouter_model: str = Field(
        default="openai/gpt-5", validation_alias="OPENROUTER_MODEL"
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", validation_alias="OPENROUTER_BASE_URL"
    )

    @property
    def model(self) -> str:
        """Resolve friendly model name from model registry."""
        from nakama_kun.ai.registry.models import get_model_identifier

        return get_model_identifier(self.openrouter_model)
