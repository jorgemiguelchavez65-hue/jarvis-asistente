"""Voz a texto en el servidor (faster-whisper): el audio solo llega a TU servidor, no a un tercero."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Protocol


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path) -> str: ...


class WhisperTranscriber:
    """Carga el modelo la primera vez que se usa y serializa las transcripciones (CPU limitada)."""

    def __init__(self, model_size: str = "small", language: str = "es"):
        self._size = model_size
        self._language = language
        self._model = None
        self._lock = threading.Lock()

    def transcribe(self, audio_path: Path) -> str:
        with self._lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise RuntimeError(
                        "Falta faster-whisper (JARVIS_STT=local). En Render usa JARVIS_STT=api; "
                        "en una máquina propia: pip install '.[audio]'") from exc
                self._model = WhisperModel(self._size, compute_type="int8")
            segments, _ = self._model.transcribe(str(audio_path), language=self._language,
                                                 vad_filter=True)
            return " ".join(s.text.strip() for s in segments)
