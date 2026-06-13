from __future__ import annotations

import contextlib
import os
import tempfile
import time
from threading import Event, Thread
from typing import Any

from nakama_kun.voice.interfaces import BaseAudioRecorder


class AudioRecorder(BaseAudioRecorder):
    """Audio recorder using sounddevice and soundfile."""

    def record(self, duration: float, device_index: int | None = None) -> str:
        """Record audio for up to `duration` seconds, or until user presses Enter."""
        try:
            import numpy as np
            import sounddevice as sd
            import soundfile as sf
        except ImportError as e:
            raise ImportError(
                "Voice dependencies are missing. "
                "Please run: pip install sounddevice soundfile numpy"
            ) from e

        sample_rate = 16000
        channels = 1
        recorded_chunks: list[np.ndarray] = []

        def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
            if status:
                from loguru import logger
                logger.warning(f"Audio recording status: {status}")
            recorded_chunks.append(indata.copy())

        stop_event = Event()

        def wait_for_keypress() -> None:
            with contextlib.suppress(KeyboardInterrupt, EOFError):
                input()
            stop_event.set()

        print("\n[Voice Mode] Recording... Speak now. Press ENTER to stop recording.")
        
        stream = sd.InputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype='int16',
            device=device_index,
            callback=callback
        )
        
        keypress_thread = Thread(target=wait_for_keypress, daemon=True)
        keypress_thread.start()

        start_time = time.time()
        with stream:
            while not stop_event.is_set():
                if time.time() - start_time >= duration:
                    print("\n[Voice Mode] Maximum recording duration reached.")
                    stop_event.set()
                time.sleep(0.1)

        if recorded_chunks:
            audio_data = np.concatenate(recorded_chunks, axis=0)
        else:
            audio_data = np.zeros((0, channels), dtype='int16')

        temp_dir = tempfile.gettempdir()
        temp_file_path = os.path.join(temp_dir, f"recording_{int(time.time())}.wav")
        sf.write(temp_file_path, audio_data, sample_rate)

        return temp_file_path
