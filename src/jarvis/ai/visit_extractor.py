"""Convierte la transcripción de una visita médica en un MedicalVisit usando Claude."""
from __future__ import annotations

from typing import Any

from jarvis.reports import MedicalVisit

SYSTEM = """Eres Jarvis, copiloto del paciente durante una visita médica.
Recibes la transcripción (puede tener errores de reconocimiento de voz y no distingue hablantes).
Extrae SOLO lo que se dijo. Reglas:
- No inventes diagnósticos, dosis ni fechas. Si algo no se mencionó, déjalo vacío.
- Si algo es ambiguo o pudo transcribirse mal (nombres de fármacos, dosis, cifras),
  inclúyelo en to_verify en lugar de afirmarlo.
- Escribe en español, en lenguaje claro para el paciente."""

TOOL = {
    "name": "registrar_visita",
    "description": "Registra los datos estructurados de la visita médica.",
    "input_schema": {
        "type": "object",
        "properties": {
            "doctor": {"type": "string"},
            "specialty": {"type": "string"},
            "reason": {"type": "string", "description": "Motivo de la consulta"},
            "diagnosis": {"type": "string"},
            "notes": {"type": "string", "description": "Resumen de lo conversado"},
            "medications": {"type": "array", "items": {"type": "string"},
                            "description": "Medicamento, dosis y frecuencia si se dijeron"},
            "follow_up": {"type": "string", "description": "Estudios, controles, indicaciones"},
            "to_verify": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["reason", "notes"],
    },
}


def extract_visit(client: Any, model: str, transcript: str, date: str) -> MedicalVisit:
    """`client` es un anthropic.Anthropic (o cualquier objeto con .messages.create)."""
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=SYSTEM,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": TOOL["name"]},
        messages=[{"role": "user", "content": f"Transcripción:\n\n{transcript}"}],
    )
    for block in response.content:
        if block.type == "tool_use":
            d = block.input
            return MedicalVisit(
                date=date,
                doctor=d.get("doctor", "No identificado"),
                specialty=d.get("specialty", "No identificada"),
                reason=d["reason"],
                notes=d.get("notes", ""),
                diagnosis=d.get("diagnosis", ""),
                medications=d.get("medications", []),
                follow_up=d.get("follow_up", ""),
                to_verify=d.get("to_verify", []),
            )
    raise RuntimeError("Claude no devolvió datos estructurados de la visita.")
