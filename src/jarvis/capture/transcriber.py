"""Voz a texto. Por defecto LOCAL (faster-whisper): el audio no sale de tu equipo."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path) -> str: ...


class WhisperTranscriber:
    def __init__(self, model_size: str = "small", language: str = "es"):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("Instala el extra de audio: pip install -e '.[audio]'") from exc
        self._model = WhisperModel(model_size, compute_type="int8")
        self._language = language

    def transcribe(self, audio_path: Path) -> str:
        segments, _ = self._model.transcribe(str(audio_path), language=self._language)
        return " ".join(s.text.strip() for s in segments)
