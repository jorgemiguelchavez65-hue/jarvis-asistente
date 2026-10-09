"""API y app web (PWA) de Jarvis."""
from __future__ import annotations

import hmac
import logging
import mimetypes
import tempfile
import time
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jarvis.ai.live_assistant import ask_live
from jarvis.config import Config
from jarvis.web.dispatch import InlineDispatcher, ThreadDispatcher
from jarvis.web.pipeline import process_visit
from jarvis.web.store import LocalStore

log = logging.getLogger("jarvis.app")
STALE_CLAIM_S = 35 * 60   # > plazo de Cloud Tasks (30 min): un intento anterior ya no puede seguir vivo
GIVE_UP_S = 90 * 60       # una visita en cola o procesando más tiempo que esto se muestra como error
STATIC = Path(__file__).parent / "static"
MAX_PART = 2 * 1024 * 1024  # un trozo son ~10 s de audio: unas decenas de KB
mimetypes.add_type("application/manifest+json", ".webmanifest")
AUDIO_EXT = {"audio/webm": "webm", "audio/mp4": "mp4", "audio/ogg": "ogg", "audio/mpeg": "mp3",
             "audio/wav": "wav", "audio/x-m4a": "m4a", "video/webm": "webm"}


class NewVisit(BaseModel):
    client: str = Field(min_length=1, max_length=200)
    contact: str = Field(default="", max_length=200)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    consent: bool


class Question(BaseModel):
    question: str = Field(default="", max_length=2000)
    image: str | None = Field(default=None, max_length=8_000_000)  # JPEG en base64


class RetryLater(Exception):
    """El intento falló pero quedan reintentos: la ruta interna responde 500 para que Cloud Tasks reintente."""


def create_app(config: Config, *, claude, transcriber, background: bool = True, store=None,
               dispatcher=None, task_verifier: Callable | None = None,
               tasks_max_attempts: int = 5) -> FastAPI:
    """`claude` es un anthropic.Anthropic; `transcriber` tiene .transcribe(path).
    `store`: LocalStore por defecto. `dispatcher`: quién pone en marcha el informe (por defecto un hilo,
    o en línea si background=False). `task_verifier`: si existe, habilita /internal/process (Cloud Tasks)."""
    if not config.access_token or len(config.access_token) < 16:
        raise RuntimeError("JARVIS_ACCESS_TOKEN debe existir y tener al menos 16 caracteres.")

    if store is None:
        store = LocalStore(config.data_dir)
        store.mark_interrupted()
    app = FastAPI(title="Jarvis", docs_url=None, redoc_url=None, openapi_url=None)

    def handle(visit_id: str, final: bool = True) -> bool:
        """Procesa una visita en cola. Devuelve False si otro ya la tomó o ya está hecha."""
        if not store.claim(visit_id, STALE_CLAIM_S):
            return False
        try:
            with tempfile.TemporaryDirectory() as tmp:
                process_visit(store, visit_id, claude=claude, model=config.model,
                              transcriber=transcriber, keep_audio=config.keep_audio, workdir=Path(tmp))
            return True
        except Exception as exc:  # noqa: BLE001
            log.exception("Fallo procesando la visita %s", visit_id)
            msg = f"{type(exc).__name__}: {exc}"[:500]
            if final:
                store.update(visit_id, status="error", error=msg)
                return False
            store.update(visit_id, status="queued", error=f"Reintentando tras un fallo: {msg}")
            raise RetryLater(msg) from exc

    if dispatcher is None:
        dispatcher = ThreadDispatcher(handle) if background else InlineDispatcher(handle)

    def auth(request: Request) -> None:
        # X-Jarvis-Token es la vía principal: Firebase Hosting/Cloud Run pueden consumir Authorization.
        header = request.headers.get("authorization", "")
        given = request.headers.get("x-jarvis-token") or (header[7:] if header.startswith("Bearer ") else "")
        if not hmac.compare_digest(given.encode(), config.access_token.encode()):
            raise HTTPException(401, "No autorizado")

    def visit_or_404(visit_id: str) -> dict:
        try:
            return store.get(visit_id)
        except KeyError:
            raise HTTPException(404, "Visita no encontrada") from None

    def launch(visit_id: str) -> None:
        store.update(visit_id, status="queued", error="")
        try:
            dispatcher.enqueue(visit_id)
        except Exception as exc:  # noqa: BLE001 - p. ej. la cola no responde: que el usuario pueda reintentar
            log.exception("No se pudo encolar %s", visit_id)
            store.update(visit_id, status="error", error=f"No se pudo iniciar el proceso: {exc}"[:500])

    api = Depends(auth)

    @app.get("/api/ping", dependencies=[api])
    def ping():
        return {"ok": True}

    @app.get("/api/visits", dependencies=[api])
    def list_visits():
        return store.list()

    @app.post("/api/visits", dependencies=[api])
    def new_visit(body: NewVisit):
        if not body.consent:
            raise HTTPException(400, "Confirma que el cliente aceptó la grabación o registro.")
        return store.create(body.client.strip(), body.contact.strip(), body.date)

    @app.get("/api/visits/{visit_id}", dependencies=[api])
    def get_visit(visit_id: str):
        v = visit_or_404(visit_id)
        if v["status"] in ("queued", "processing") and time.time() - v.get("updated_at", 0) > GIVE_UP_S:
            v = store.update(visit_id, status="error",
                             error="El proceso tardó demasiado y se detuvo. Pulsa Reintentar.")
        return v

    @app.delete("/api/visits/{visit_id}", dependencies=[api])
    def delete_visit(visit_id: str):
        visit_or_404(visit_id)
        store.delete(visit_id)
        return {"ok": True}

    @app.post("/api/visits/{visit_id}/ask", dependencies=[api])
    def ask(visit_id: str, body: Question):
        visit = visit_or_404(visit_id)
        if not body.question.strip() and not body.image:
            raise HTTPException(400, "Escribe una pregunta o adjunta una foto.")
        try:
            answer = ask_live(claude, config.model, visit["consulted"], body.question.strip(), body.image)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"Jarvis no pudo responder: {exc}") from exc
        item = {"question": body.question.strip() or "(foto)", "answer": answer,
                "photo": bool(body.image)}
        store.append_consulted(visit_id, item)
        return item

    @app.put("/api/visits/{visit_id}/audio/{session}/{seq}", dependencies=[api])
    async def put_audio_part(visit_id: str, session: int, seq: int, request: Request):
        visit = visit_or_404(visit_id)
        if visit["status"] not in ("open", "error"):
            raise HTTPException(409, "Esta visita ya no admite audio.")
        if not (0 <= session < 10**13 and 0 <= seq < 10**6):
            raise HTTPException(400, "Trozo inválido.")
        ext = AUDIO_EXT.get((request.headers.get("content-type") or "").split(";")[0].strip())
        if ext is None:
            raise HTTPException(415, "Formato de audio no admitido.")
        data = await request.body()
        if not data or len(data) > MAX_PART:
            raise HTTPException(413 if data else 400, "Trozo vacío o demasiado grande.")
        try:
            store.save_part(visit_id, session, seq, ext, data, config.max_audio_mb * 1024 * 1024)
        except ValueError:
            raise HTTPException(413, f"El audio supera {config.max_audio_mb} MB.") from None
        return {"ok": True}

    @app.post("/api/visits/{visit_id}/finish", dependencies=[api])
    def finish(visit_id: str, notes: str = Form(default="")):
        visit = visit_or_404(visit_id)
        if visit["status"] in ("queued", "processing"):
            raise HTTPException(409, "Esta visita ya se está procesando.")
        store.update(visit_id, notes=notes.strip() or visit["notes"])
        launch(visit_id)
        return {"status": store.get(visit_id)["status"]}

    if task_verifier is not None:
        @app.post("/internal/process/{visit_id}")
        def process_task(visit_id: str, request: Request):
            """Lo llama Cloud Tasks (no el teléfono). 5xx = Cloud Tasks reintenta con espera."""
            task_verifier(request)
            try:
                store.get(visit_id)
            except KeyError:
                return {"skipped": "visita borrada"}      # 2xx: no tiene sentido reintentar
            attempt = int(request.headers.get("x-cloudtasks-taskretrycount", "0")) + 1
            try:
                ran = handle(visit_id, final=attempt >= tasks_max_attempts)
            except RetryLater:
                raise HTTPException(500, "Fallo; se reintentará") from None
            if not ran and store.get(visit_id)["status"] == "processing":
                raise HTTPException(500, "Otro intento sigue en curso; se reintentará")
            return {"processed": ran}

    @app.exception_handler(HTTPException)
    async def http_error(_, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.middleware("http")
    async def no_store_api(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app
