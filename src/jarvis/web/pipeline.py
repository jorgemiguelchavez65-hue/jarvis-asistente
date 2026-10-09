"""Procesa una visita terminada: transcribe, genera el informe y limpia el audio."""
from __future__ import annotations

from pathlib import Path

from jarvis.ai.visit_extractor import extract_visit
from jarvis.reports import render_report


def process_visit(store, visit_id: str, *, claude, model: str, transcriber, keep_audio: bool,
                  workdir: Path) -> None:
    """Lanza la excepción si algo falla: quien la llama decide si reintentar o marcar error."""
    visit = store.get(visit_id)
    files = store.materialize_audio(visit_id, workdir)
    if files:
        transcript = "\n".join(t for t in (transcriber.transcribe(f).strip() for f in files) if t)
        visit = store.update(visit_id, transcript=transcript)  # se guarda antes de llamar a Claude
        if not keep_audio:
            store.discard_audio(visit_id)
    # Si el audio ya se transcribió en un intento anterior, se reutiliza la transcripción guardada.
    report = extract_visit(
        claude, model, date=visit["date"], client_name=visit["client"], contact=visit["contact"],
        transcript=visit["transcript"], notes=visit["notes"], consulted=visit["consulted"],
    )
    store.update(visit_id, status="done", error="", report=report.to_dict(),
                 report_md=render_report(report))
