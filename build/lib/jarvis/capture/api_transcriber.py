"""Voz a texto por API compatible con OpenAI (POST <base>/audio/transcriptions).

Sirve para varios proveedores (OpenAI, Groq, etc.) cambiando solo la URL, la clave y el modelo.
OJO: el audio de la visita SALE de tu servidor hacia ese proveedor.
"""
from __future__ import annotations

import time
from pathlib import Path

import httpx

RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}
AUDIO_TYPES = {".webm": "audio/webm", ".mp4": "audio/mp4", ".m4a": "audio/mp4", ".ogg": "audio/ogg",
               ".mp3": "audio/mpeg", ".wav": "audio/wav"}  # mimetypes adivina video/webm
MAX_FILE_MB = 25  # tope habitual de estas APIs; ~100 minutos de audio a 32 kbps


class TranscriptionError(RuntimeError):
    pass


class ApiTranscriber:
    def __init__(self, base_url: str, api_key: str, model: str, language: str = "es",
                 client: httpx.Client | None = None, retries: int = 3, backoff: float = 5.0):
        self._url = base_url.rstrip("/") + "/audio/transcriptions"
        self._key, self._model, self._lang = api_key, model, language
        self._client = client or httpx.Client(timeout=httpx.Timeout(600.0, connect=20.0))
        self._retries, self._backoff = retries, backoff

    def transcribe(self, audio_path: Path) -> str:
        size_mb = audio_path.stat().st_size / (1024 * 1024)
        if size_mb > MAX_FILE_MB:
            raise TranscriptionError(
                f"Una grabación pesa {size_mb:.0f} MB y el servicio de voz admite {MAX_FILE_MB} MB. "
                "Detén la grabación y empieza otra cada ~90 minutos.")
        ctype = AUDIO_TYPES.get(audio_path.suffix.lower(), "application/octet-stream")
        last = ""
        for attempt in range(self._retries):
            try:
                with audio_path.open("rb") as fh:
                    r = self._client.post(
                        self._url, headers={"Authorization": f"Bearer {self._key}"},
                        data={"model": self._model, "language": self._lang, "response_format": "text"},
                        files={"file": (audio_path.name, fh, ctype)})
            except httpx.TransportError as exc:
                last = f"{type(exc).__name__}: {exc}"
            else:
                if r.status_code == 200:
                    return r.text.strip()
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                if r.status_code not in RETRY_STATUS:
                    break  # clave inválida, formato no admitido…: reintentar no ayuda
            if attempt + 1 < self._retries:
                time.sleep(self._backoff * (attempt + 1))
        raise TranscriptionError(f"La transcripción falló ({last})")
