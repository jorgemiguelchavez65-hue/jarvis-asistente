"""Interfaz de línea de comandos: `jarvis <comando>`."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from jarvis.config import Config
from jarvis.reports import MedicalVisit, render_report
from jarvis.routine import TaskManager
from jarvis.storage import JsonStore


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jarvis", description="Asistente personal Jarvis")
    sub = p.add_subparsers(dest="command", required=True)

    add = sub.add_parser("agregar", help="Agregar una tarea")
    add.add_argument("titulo")
    add.add_argument("--hora", help="HH:MM")
    add.add_argument("--dia", help="AAAA-MM-DD (por defecto hoy)")

    sub.add_parser("hoy", help="Ver la rutina de hoy")

    done = sub.add_parser("hecho", help="Marcar tarea como completada")
    done.add_argument("id", type=int)

    rep = sub.add_parser("informe", help="Generar informe de visita médica")
    rep.add_argument("--fecha", default=date.today().isoformat())
    rep.add_argument("--medico", required=True)
    rep.add_argument("--especialidad", required=True)
    rep.add_argument("--motivo", required=True)
    rep.add_argument("--diagnostico", default="")
    rep.add_argument("--notas", default="")
    rep.add_argument("--medicacion", action="append", default=[])
    rep.add_argument("--seguimiento", default="")

    vis = sub.add_parser("visita", help="Copiloto de visita: audio/transcripción -> informe con Claude")
    src = vis.add_mutually_exclusive_group(required=True)
    src.add_argument("--grabar", action="store_true", help="Grabar del micrófono hasta Ctrl+C")
    src.add_argument("--audio", type=Path, help="Archivo de audio ya grabado")
    src.add_argument("--transcripcion", type=Path, help="Archivo de texto con la transcripción")
    vis.add_argument("--fecha", default=date.today().isoformat())
    vis.add_argument("--conservar-audio", action="store_true", help="No borrar el audio al terminar")
    vis.add_argument("--yo-confirmo-consentimiento", action="store_true",
                     help="Saltar la pregunta de consentimiento de grabación")

    ask = sub.add_parser("preguntar", help="Preguntar a Claude (requiere API key)")
    ask.add_argument("pregunta")
    return p


def run_visit(args, config: Config) -> int:
    from jarvis.ai import ClaudeClient, ClaudeNotConfigured

    try:
        claude = ClaudeClient(config)  # falla pronto, antes de grabar nada
    except ClaudeNotConfigured as exc:
        print(f"Error: {exc}")
        return 1

    audio: Path | None = args.audio
    if args.grabar:
        if not args.yo_confirmo_consentimiento:
            ok = input("¿El médico sabe y acepta que se grabe la consulta? [s/N] ")
            if ok.strip().lower() not in ("s", "si", "sí"):
                print("Cancelado: sin consentimiento no se graba.")
                return 1
        from jarvis.capture import record_until_interrupt

        audio = record_until_interrupt(config.data_dir / f"visita_{args.fecha}.wav")

    if audio:
        from jarvis.capture import WhisperTranscriber

        print("Transcribiendo localmente…")
        transcript = WhisperTranscriber().transcribe(audio)
        if args.grabar and not args.conservar_audio:
            audio.unlink(missing_ok=True)
    else:
        transcript = args.transcripcion.read_text(encoding="utf-8")

    print("Generando informe con Claude…")
    visit = claude.visit_from_transcript(transcript, args.fecha)
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    out = config.reports_dir / f"visita_{visit.date}.md"
    out.write_text(render_report(visit), encoding="utf-8")
    print(f"Informe guardado en {out}")
    if visit.to_verify:
        print(f"Atención: {len(visit.to_verify)} punto(s) por verificar con el médico.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config.load()
    tasks = TaskManager(JsonStore(config.data_dir / "tareas.json"))

    if args.command == "agregar":
        day = date.fromisoformat(args.dia) if args.dia else None
        t = tasks.add(args.titulo, day, args.hora)
        print(f"Tarea #{t.id} agregada.")
    elif args.command == "hoy":
        todays = tasks.for_day()
        if not todays:
            print("Nada programado para hoy.")
        for t in todays:
            mark = "x" if t.done else " "
            print(f"[{mark}] #{t.id} {t.time or '--:--'} {t.title}")
    elif args.command == "hecho":
        t = tasks.complete(args.id)
        print(f"Completada: {t.title}")
    elif args.command == "informe":
        visit = MedicalVisit(
            date=args.fecha, doctor=args.medico, specialty=args.especialidad,
            reason=args.motivo, notes=args.notas, diagnosis=args.diagnostico,
            medications=args.medicacion, follow_up=args.seguimiento,
        )
        config.reports_dir.mkdir(parents=True, exist_ok=True)
        out = config.reports_dir / f"visita_{visit.date}.md"
        out.write_text(render_report(visit), encoding="utf-8")
        print(f"Informe guardado en {out}")
    elif args.command == "visita":
        return run_visit(args, config)
    elif args.command == "preguntar":
        from jarvis.ai import ClaudeClient, ClaudeNotConfigured

        try:
            print(ClaudeClient(config).ask(args.pregunta))
        except ClaudeNotConfigured as exc:
            print(f"Error: {exc}")
            return 1
    return 0
