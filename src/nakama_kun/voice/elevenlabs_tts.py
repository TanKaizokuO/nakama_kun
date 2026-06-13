from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request

from nakama_kun.ai.exceptions import AIError, APIKeyNotFoundError
from nakama_kun.config.voice import VoiceSettings
from nakama_kun.voice.interfaces import BaseTextToSpeech


class ElevenLabsTTS(BaseTextToSpeech):
    """ElevenLabs Text-to-Speech synthesizer using urllib and asyncio.to_thread."""

    def __init__(self, settings: VoiceSettings) -> None:
        self.settings = settings

    async def synthesize(self, text: str) -> bytes:
        """Synthesize text into speech audio bytes (MP3)."""
        api_key = None
        if self.settings.voice_elevenlabs_api_key:
            api_key = self.settings.voice_elevenlabs_api_key.get_secret_value()

        if not api_key:
            import os
            api_key = os.getenv("ELEVENLABS_API_KEY")

        if not api_key:
            raise APIKeyNotFoundError("ElevenLabs API key not found for speech synthesis.")

        url = f"{self.settings.voice_elevenlabs_api_base}/text-to-speech/{self.settings.voice_elevenlabs_voice_id}"
        
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "accept": "audio/mpeg",
        }
        
        data = {
            "text": text,
            "model_id": self.settings.voice_elevenlabs_model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            }
        }
        
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        
        def _send_request() -> bytes:
            try:
                with urllib.request.urlopen(req, timeout=15) as response:
                    res = response.read()
                    if isinstance(res, bytes):
                        return res
                    raise TypeError("Expected bytes response from ElevenLabs API")
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                raise AIError(f"ElevenLabs API Error (HTTP {e.code}): {err_body}") from e
            except Exception as e:
                raise AIError(f"ElevenLabs Connection Error: {e}") from e

        return await asyncio.to_thread(_send_request)
