"""API y app web (PWA) de Jarvis."""
from __future__ import annotations

import hmac
import mimetypes
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jarvis.ai.live_assistant import ask_live
from jarvis.config import Config
from jarvis.web.pipeline import process_visit
from jarvis.web.store import VisitStore

STATIC = Path(__file__).parent / "static"
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


def create_app(config: Config, *, claude, transcriber, background: bool = True) -> FastAPI:
    """`claude` es un anthropic.Anthropic; `transcriber` tiene .transcribe(path).
    `background=False` ejecuta el proceso en línea (para los tests)."""
    if not config.access_token or len(config.access_token) < 16:
        raise RuntimeError("JARVIS_ACCESS_TOKEN debe existir y tener al menos 16 caracteres.")

    store = VisitStore(config.data_dir)
    store.mark_interrupted()
    app = FastAPI(title="Jarvis", docs_url=None, redoc_url=None, openapi_url=None)

    def auth(request: Request) -> None:
        header = request.headers.get("authorization", "")
        given = header[7:] if header.startswith("Bearer ") else ""
        if not hmac.compare_digest(given.encode(), config.access_token.encode()):
            raise HTTPException(401, "No autorizado")

    def visit_or_404(visit_id: str) -> dict:
        try:
            return store.get(visit_id)
        except KeyError:
            raise HTTPException(404, "Visita no encontrada") from None

    def launch(visit_id: str) -> None:
        store.update(visit_id, status="processing", error="")
        job = lambda: process_visit(store, visit_id, claude=claude, model=config.model,  # noqa: E731
                                    transcriber=transcriber, keep_audio=config.keep_audio)
        if background:
            threading.Thread(target=job, daemon=True).start()
        else:
            job()

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
        return visit_or_404(visit_id)

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

    @app.post("/api/visits/{visit_id}/finish", dependencies=[api])
    async def finish(visit_id: str, notes: str = Form(default=""), audio: UploadFile | None = File(default=None)):
        visit = visit_or_404(visit_id)
        if visit["status"] == "processing":
            raise HTTPException(409, "Esta visita ya se está procesando.")
        if audio is not None and audio.filename != "":
            ext = AUDIO_EXT.get((audio.content_type or "").split(";")[0].strip())
            if ext is None:
                raise HTTPException(415, "Formato de audio no admitido.")
            limit = config.max_audio_mb * 1024 * 1024
            for f in store.audio_files(visit_id):
                f.unlink(missing_ok=True)
            dest = store.audio_dir / f"{visit_id}.{ext}"
            size = 0
            with dest.open("wb") as out:
                while chunk := await audio.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        out.close()
                        dest.unlink(missing_ok=True)
                        raise HTTPException(413, f"El audio supera {config.max_audio_mb} MB.")
                    out.write(chunk)
        store.update(visit_id, notes=notes.strip() or visit["notes"])
        launch(visit_id)
        return {"status": "processing"}

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
