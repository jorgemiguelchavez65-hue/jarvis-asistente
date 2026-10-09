"""Procesa una visita terminada: transcribe, genera el informe y limpia el audio."""
from __future__ import annotations

import logging

from jarvis.ai.visit_extractor import extract_visit
from jarvis.reports import render_report
from jarvis.web.store import VisitStore

log = logging.getLogger("jarvis.pipeline")


def process_visit(store: VisitStore, visit_id: str, *, claude, model: str, transcriber,
                  keep_audio: bool) -> None:
    """Pensado para correr en un hilo. Nunca lanza: deja el resultado o el error en la visita."""
    try:
        visit = store.get(visit_id)
        audio = store.audio_files(visit_id)
        if audio:
            transcript = transcriber.transcribe(audio[0])
            visit = store.update(visit_id, transcript=transcript)  # se guarda antes de llamar a Claude
            if not keep_audio:
                for f in audio:
                    f.unlink(missing_ok=True)
        report = extract_visit(
            claude, model, date=visit["date"], client_name=visit["client"], contact=visit["contact"],
            transcript=visit["transcript"], notes=visit["notes"], consulted=visit["consulted"],
        )
        store.update(visit_id, status="done", error="", report=report.to_dict(),
                     report_md=render_report(report))
    except Exception as exc:  # noqa: BLE001 - el usuario debe ver el fallo y poder reintentar
        log.exception("Fallo procesando la visita %s", visit_id)
        store.update(visit_id, status="error", error=f"{type(exc).__name__}: {exc}"[:500])
