from __future__ import annotations

from abc import ABC, abstractmethod


class BaseSpeechToText(ABC):
    """Abstract base class for Speech-to-Text (transcription) engines."""

    @abstractmethod
    async def transcribe(self, file_path: str) -> str:
        """Transcribe the audio file at the given path to text."""
        pass


class BaseTextToSpeech(ABC):
    """Abstract base class for Text-to-Speech (synthesis) engines."""

    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """Synthesize the given text to speech audio bytes (MP3/WAV)."""
        pass


class BaseAudioRecorder(ABC):
    """Abstract base class for audio recorders."""

    @abstractmethod
    def record(self, duration: float, device_index: int | None = None) -> str:
        """Record audio for the specified duration and return the path to the recorded file."""
        pass


class BaseAudioPlayer(ABC):
    """Abstract base class for audio players."""

    @abstractmethod
    def play(self, audio_data: bytes) -> None:
        """Play back the raw audio bytes (MP3/WAV)."""
        pass
