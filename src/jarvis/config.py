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
    backend: str  # "local" (archivos, hilo) o "gcp" (Firestore, Cloud Storage, Cloud Tasks)
    gcp_project: str | None
    audio_bucket: str | None
    tasks_queue: str
    tasks_location: str
    tasks_sa: str | None  # cuenta de servicio que firma el token de Cloud Tasks
    service_url: str | None  # URL propia de Cloud Run (destino de las tareas)
    tasks_max_attempts: int

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
            backend=env.get("JARVIS_BACKEND", "local"),
            gcp_project=env.get("GOOGLE_CLOUD_PROJECT") or None,
            audio_bucket=env.get("JARVIS_AUDIO_BUCKET") or None,
            tasks_queue=env.get("JARVIS_TASKS_QUEUE", "jarvis-process"),
            tasks_location=env.get("JARVIS_TASKS_LOCATION", "us-central1"),
            tasks_sa=env.get("JARVIS_TASKS_SA") or None,
            service_url=env.get("JARVIS_SERVICE_URL") or None,
            tasks_max_attempts=int(env.get("JARVIS_TASKS_MAX_ATTEMPTS", "5")),
        )
