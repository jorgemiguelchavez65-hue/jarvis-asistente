"""Punto de entrada del servidor: `jarvis-server` o `python -m jarvis.web.main`."""
from __future__ import annotations

import os

from jarvis.ai import ClaudeClient
from jarvis.config import Config
from jarvis.web.app import create_app


def build_transcriber(config: Config):
    if config.stt == "api":
        missing = [n for n, v in {"JARVIS_STT_BASE_URL": config.stt_base_url,
                                  "JARVIS_STT_API_KEY": config.stt_api_key,
                                  "JARVIS_STT_MODEL": config.stt_model}.items() if not v]
        if missing:
            raise RuntimeError("Faltan variables para JARVIS_STT=api: " + ", ".join(missing))
        from jarvis.capture.api_transcriber import ApiTranscriber

        return ApiTranscriber(config.stt_base_url, config.stt_api_key, config.stt_model)
    if config.stt != "local":
        raise RuntimeError("JARVIS_STT debe ser 'local' o 'api'.")
    from jarvis.capture import WhisperTranscriber

    return WhisperTranscriber(config.whisper_model)


def build_store(config: Config):
    if config.backend == "postgres":
        if not config.database_url:
            raise RuntimeError("Falta DATABASE_URL para JARVIS_BACKEND=postgres.")
        from jarvis.web.pg_store import PostgresStore

        return PostgresStore(config.database_url)
    if config.backend != "local":
        raise RuntimeError("JARVIS_BACKEND debe ser 'local' o 'postgres'.")
    return None  # create_app usa LocalStore


def build_app():
    config = Config.load()
    transcriber = build_transcriber(config)  # primero lo barato: falla pronto si falta configuración
    store = build_store(config)
    return create_app(config, claude=ClaudeClient(config).raw, transcriber=transcriber, store=store)


def main() -> None:
    import uvicorn

    uvicorn.run(build_app(), host=os.environ.get("HOST", "0.0.0.0"),
                port=int(os.environ.get("PORT", "10000")), proxy_headers=True,
                forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
