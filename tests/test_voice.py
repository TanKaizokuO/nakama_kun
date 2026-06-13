from __future__ import annotations

import io
import urllib.error
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest
from pydantic import SecretStr

from nakama_kun.ai.exceptions import AIError, APIKeyNotFoundError
from nakama_kun.config.voice import VoiceSettings
from nakama_kun.voice.elevenlabs_tts import ElevenLabsTTS
from nakama_kun.voice.player import AudioPlayer
from nakama_kun.voice.whisper_stt import WhisperSTT


@pytest.fixture
def voice_settings() -> VoiceSettings:
    settings = VoiceSettings()
    settings.voice_openai_api_key = SecretStr("mock-openai-key")
    settings.voice_elevenlabs_api_key = SecretStr("mock-elevenlabs-key")
    settings.voice_enabled = True
    return settings


@pytest.mark.anyio
async def test_whisper_stt_success(voice_settings: VoiceSettings) -> None:
    stt = WhisperSTT(voice_settings)

    mock_resp = MagicMock()
    mock_resp.text = "Hello world"

    # We mock client.audio.transcriptions.create via patching AsyncOpenAI
    with patch("nakama_kun.voice.whisper_stt.AsyncOpenAI") as mock_openai_class:
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_resp)

        with patch("builtins.open", mock_open()) as mock_file:
            result = await stt.transcribe("dummy_path.wav")
            assert result == "Hello world"
            mock_client.audio.transcriptions.create.assert_called_once()


@pytest.mark.anyio
async def test_whisper_stt_missing_api_key() -> None:
    settings = VoiceSettings()
    settings.voice_openai_api_key = None
    stt = WhisperSTT(settings)

    with patch("os.getenv", return_value=None), patch("nakama_kun.ai.config.AISettings") as mock_ai:
        mock_ai_instance = MagicMock()
        mock_ai_instance.openrouter_api_key = None
        mock_ai.return_value = mock_ai_instance
        
        with pytest.raises(APIKeyNotFoundError):
            await stt.transcribe("dummy.wav")


@pytest.mark.anyio
async def test_elevenlabs_tts_success(voice_settings: VoiceSettings) -> None:
    tts = ElevenLabsTTS(voice_settings)

    mock_resp = io.BytesIO(b"audio-mpeg-bytes")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        result = await tts.synthesize("Hello")
        assert result == b"audio-mpeg-bytes"


@pytest.mark.anyio
async def test_elevenlabs_tts_http_error(voice_settings: VoiceSettings) -> None:
    tts = ElevenLabsTTS(voice_settings)

    # Mock an HTTPError
    mock_error = urllib.error.HTTPError(
        url="http://mock-url",
        code=400,
        msg="Bad Request",
        hdrs=None,  # type: ignore
        fp=io.BytesIO(b"Invalid request payload"),
    )

    with patch("urllib.request.urlopen", side_effect=mock_error):
        with pytest.raises(AIError) as exc_info:
            await tts.synthesize("Hello")
        assert "ElevenLabs API Error" in str(exc_info.value)


def test_audio_player_fallback_failure() -> None:
    player = AudioPlayer()

    # Mock shutil.which to return None for all system players
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError) as exc_info:
            player.play(b"mock-audio")
        assert "No system audio player found" in str(exc_info.value)


@pytest.mark.anyio
async def test_voice_mode_routing_and_speak_fallback() -> None:
    from nakama_kun.ai.services.chat_service import ChatService
    from nakama_kun.modes.agent_mode import AgentMode
    from nakama_kun.modes.ask_mode import AskMode
    from nakama_kun.modes.plan_mode import PlanMode
    from nakama_kun.voice.voice_mode import VoiceMode

    mock_chat = MagicMock(spec=ChatService)
    mock_agent = MagicMock(spec=AgentMode)
    mock_plan = MagicMock(spec=PlanMode)
    mock_ask = MagicMock(spec=AskMode)

    settings = VoiceSettings()
    settings.voice_openai_api_key = SecretStr("key")
    settings.voice_elevenlabs_api_key = SecretStr("key")
    settings.voice_enabled = True

    mode = VoiceMode(mock_chat, mock_agent, mock_plan, mock_ask, settings)

    # Mock synthesize to raise an exception to test speech fallback
    mode._tts.synthesize = AsyncMock(side_effect=Exception("API limit"))

    with patch("nakama_kun.ui.console.console.print") as mock_print:
        await mode._speak_text("Hello user.")
        # Fallback console prints should be called
        mock_print.assert_any_call("[bold yellow](Speech unavailable: Hello user.)[/bold yellow]")
