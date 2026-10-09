"""Punto de entrada del servidor: `jarvis-server` o `python -m jarvis.web.main`."""
from __future__ import annotations

import os

from jarvis.ai import ClaudeClient
from jarvis.capture import WhisperTranscriber
from jarvis.config import Config
from jarvis.web.app import create_app


def build_app():
    config = Config.load()
    claude = ClaudeClient(config).raw
    transcriber = WhisperTranscriber(config.whisper_model)
    if config.backend != "gcp":
        return create_app(config, claude=claude, transcriber=transcriber)

    missing = [n for n, v in {"GOOGLE_CLOUD_PROJECT": config.gcp_project,
                              "JARVIS_AUDIO_BUCKET": config.audio_bucket,
                              "JARVIS_SERVICE_URL": config.service_url,
                              "JARVIS_TASKS_SA": config.tasks_sa}.items() if not v]
    if missing:
        raise RuntimeError("Faltan variables para JARVIS_BACKEND=gcp: " + ", ".join(missing))
    from google.cloud import firestore, storage, tasks_v2

    from jarvis.web.dispatch import CloudTasksDispatcher, make_task_verifier
    from jarvis.web.firestore_store import FirestoreStore

    store = FirestoreStore(firestore.Client(project=config.gcp_project),
                           storage.Client(project=config.gcp_project).bucket(config.audio_bucket))
    dispatcher = CloudTasksDispatcher(
        tasks_v2.CloudTasksClient(), project=config.gcp_project, location=config.tasks_location,
        queue=config.tasks_queue, service_url=config.service_url, service_account=config.tasks_sa)
    return create_app(config, claude=claude, transcriber=transcriber, store=store,
                      dispatcher=dispatcher,
                      task_verifier=make_task_verifier(config.service_url, config.tasks_sa),
                      tasks_max_attempts=config.tasks_max_attempts)


def main() -> None:
    import uvicorn

    uvicorn.run(build_app(), host=os.environ.get("HOST", "0.0.0.0"),
                port=int(os.environ.get("PORT", "8080")), proxy_headers=True,
                forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
