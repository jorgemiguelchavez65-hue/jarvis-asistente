"""Punto de entrada del servidor: `jarvis-server` o `python -m jarvis.web.main`."""
from __future__ import annotations

import os

from jarvis.ai import ClaudeClient
from jarvis.capture import WhisperTranscriber
from jarvis.config import Config
from jarvis.web.app import create_app


def build_app():
    config = Config.load()
    claude = ClaudeClient(config)
    return create_app(config, claude=claude.raw,
                      transcriber=WhisperTranscriber(config.whisper_model))


def main() -> None:
    import uvicorn

    uvicorn.run(build_app(), host=os.environ.get("HOST", "0.0.0.0"),
                port=int(os.environ.get("PORT", "8080")), proxy_headers=True,
                forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
