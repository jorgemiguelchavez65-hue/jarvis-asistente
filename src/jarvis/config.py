"""Configuración central: rutas y variables de entorno."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data_dir: Path
    anthropic_api_key: str | None
    model: str
    access_token: str | None  # contraseña de la app web
    whisper_model: str
    keep_audio: bool
    max_audio_mb: int

    @classmethod
    def load(cls) -> "Config":
        env = os.environ
        return cls(
            data_dir=Path(env.get("JARVIS_DATA_DIR", "data")).resolve(),
            anthropic_api_key=env.get("ANTHROPIC_API_KEY") or None,
            model=env.get("JARVIS_MODEL", "claude-sonnet-5-5"),
            access_token=env.get("JARVIS_ACCESS_TOKEN") or None,
            whisper_model=env.get("JARVIS_WHISPER_MODEL", "small"),
            keep_audio=env.get("JARVIS_KEEP_AUDIO", "0") == "1",
            max_audio_mb=int(env.get("JARVIS_MAX_AUDIO_MB", "60")),
        )
