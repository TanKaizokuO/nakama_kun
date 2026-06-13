from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from nakama_kun.config import find_env_file


class VoiceSettings(BaseSettings):
    """Configuration settings for nakama_kun's Voice Interface."""

    model_config = SettingsConfigDict(
        env_file=find_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API Keys (secrets)
    voice_openai_api_key: SecretStr | None = Field(
        default=None, validation_alias="VOICE_OPENAI_API_KEY"
    )
    voice_elevenlabs_api_key: SecretStr | None = Field(
        default=None, validation_alias="VOICE_ELEVENLABS_API_KEY"
    )

    # Custom Endpoint API Bases
    voice_openai_api_base: str = Field(
        default="https://api.openai.com/v1", validation_alias="VOICE_OPENAI_API_BASE"
    )
    voice_elevenlabs_api_base: str = Field(
        default="https://api.elevenlabs.io/v1", validation_alias="VOICE_ELEVENLABS_API_BASE"
    )

    # Models & Voice IDs
    voice_whisper_model: str = Field(
        default="whisper-1", validation_alias="VOICE_WHISPER_MODEL"
    )
    voice_elevenlabs_voice_id: str = Field(
        default="21m00Tcm4TlvDq8ikWAM", validation_alias="VOICE_ELEVENLABS_VOICE_ID"
    )
    voice_elevenlabs_model_id: str = Field(
        default="eleven_monolingual_v1", validation_alias="VOICE_ELEVENLABS_MODEL_ID"
    )

    # Global Enable / Disable
    voice_enabled: bool = Field(
        default=False, validation_alias="VOICE_ENABLED"
    )

    # Optional audio device selection
    voice_audio_device_index: int | None = Field(
        default=None, validation_alias="VOICE_AUDIO_DEVICE_INDEX"
    )
