from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile

from nakama_kun.voice.interfaces import BaseAudioPlayer


class AudioPlayer(BaseAudioPlayer):
    """Audio player using OS command-line players (ffplay, mpg123, etc.) as fallback."""

    def play(self, audio_data: bytes) -> None:
        """Play back ElevenLabs MP3 data."""
        temp_dir = tempfile.gettempdir()
        temp_file_path = os.path.join(temp_dir, "nakama_speech.mp3")
        with open(temp_file_path, "wb") as f:
            f.write(audio_data)

        players = [
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", temp_file_path],
            ["mpg123", "-q", temp_file_path],
            ["mpv", "--no-video", temp_file_path],
        ]

        played = False
        for cmd in players:
            try:
                if shutil.which(cmd[0]):
                    subprocess.run(cmd, check=True)
                    played = True
                    break
            except Exception:
                pass

        # Cleanup
        if os.path.exists(temp_file_path):
            with contextlib.suppress(Exception):
                os.remove(temp_file_path)

        if not played:
            raise RuntimeError("No system audio player found (tried ffplay, mpg123, mpv).")
