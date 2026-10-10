"""Convierte lo captado en una visita (transcripción, notas, consultas) en un FieldVisit."""
from __future__ import annotations

from typing import Any

from jarvis.reports import FieldVisit

SYSTEM = """Eres Jarvis, asistente de un profesional que visita médicos y laboratorios por trabajo.
Recibes la transcripción de la visita (con errores de reconocimiento de voz posibles y sin
separar hablantes), notas rápidas del usuario y consultas que hizo durante la visita.
Redacta el informe SOLO con lo que consta en esos datos. Reglas:
- No inventes compromisos, fechas, cifras, precios ni nombres. Si no se dijo, déjalo vacío.
- Los nombres de equipos, reactivos, marcas y cifras mal transcritos van a to_verify, no al informe como hechos.
- Distingue compromisos (alguien se obligó a algo) de necesidades (algo que el cliente expresó).
- Privacidad: no incluyas datos identificables de pacientes (nombres, documentos, historias clínicas).
  Si se mencionaron, omítelos y deja constancia en to_verify de que se omitieron.
- Español claro y breve."""

TOOL = {
    "name": "registrar_visita",
    "description": "Registra el informe estructurado de la visita.",
    "input_schema": {
        "type": "object",
        "properties": {
            "contact": {"type": "string", "description": "Persona con quien se habló, si se menciona"},
            "summary": {"type": "string", "description": "Resumen de 3 a 6 líneas"},
            "topics": {"type": "array", "items": {
                "type": "object",
                "properties": {"item": {"type": "string"}, "detail": {"type": "string"}},
                "required": ["item", "detail"]}},
            "needs": {"type": "array", "items": {"type": "string"}},
            "commitments": {"type": "array", "items": {
                "type": "object",
                "properties": {"what": {"type": "string"}, "who": {"type": "string"},
                               "when": {"type": "string"}},
                "required": ["what"]}},
            "next_steps": {"type": "array", "items": {"type": "string"}},
            "to_verify": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary"],
    },
}


def extract_visit(client: Any, model: str, *, date: str, client_name: str, contact: str = "",
                  transcript: str = "", notes: str = "", consulted: list[dict] | None = None
                  ) -> FieldVisit:
    """`client` es un anthropic.Anthropic (o cualquier objeto con .messages.create)."""
    consulted = consulted or []
    parts = [f"Cliente: {client_name}", f"Fecha: {date}"]
    if contact:
        parts.append(f"Contacto indicado por el usuario: {contact}")
    parts.append(f"Transcripción de la visita:\n{transcript or '(no hubo grabación)'}")
    if notes:
        parts.append(f"Notas rápidas del usuario:\n{notes}")
    if consulted:
        parts.append("Consultas hechas durante la visita:\n" + "\n".join(
            f"- {c['question']} → {c['answer']}" for c in consulted))
    response = client.messages.create(
        model=model, max_tokens=3000, system=SYSTEM,
        tools=[TOOL], tool_choice={"type": "tool", "name": TOOL["name"]},
        messages=[{"role": "user", "content": "\n\n".join(parts)}],
    )
    for block in response.content:
        if block.type == "tool_use":
            d = block.input
            return FieldVisit(
                date=date, client=client_name, contact=d.get("contact") or contact,
                summary=d.get("summary", ""), topics=d.get("topics", []), needs=d.get("needs", []),
                commitments=d.get("commitments", []), next_steps=d.get("next_steps", []),
                to_verify=d.get("to_verify", []), consulted=consulted,
            )
    raise RuntimeError("Claude no devolvió datos estructurados de la visita.")
