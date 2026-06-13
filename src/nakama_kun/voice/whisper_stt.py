from __future__ import annotations

import os

from openai import AsyncOpenAI

from nakama_kun.ai.exceptions import APIKeyNotFoundError
from nakama_kun.config.voice import VoiceSettings
from nakama_kun.voice.interfaces import BaseSpeechToText


class WhisperSTT(BaseSpeechToText):
    """Whisper Speech-to-Text transcriber using AsyncOpenAI."""

    def __init__(self, settings: VoiceSettings) -> None:
        self.settings = settings

    async def transcribe(self, file_path: str) -> str:
        """Transcribe audio file to text."""
        # 1. Resolve API key
        api_key = None
        if self.settings.voice_openai_api_key:
            api_key = self.settings.voice_openai_api_key.get_secret_value()
        
        # Fallbacks
        if not api_key:
            from nakama_kun.ai.config import AISettings
            try:
                ai_settings = AISettings()
                if ai_settings.openrouter_api_key:
                    api_key = ai_settings.openrouter_api_key.get_secret_value()
            except Exception:
                pass
        
        if not api_key:
            api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise APIKeyNotFoundError("OpenAI/OpenRouter API key not found for transcription.")

        # 2. Call OpenAI transcription API
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=self.settings.voice_openai_api_base,
        )
        
        with open(file_path, "rb") as audio_file:
            response = await client.audio.transcriptions.create(
                model=self.settings.voice_whisper_model,
                file=audio_file,
            )
        
        return response.text
