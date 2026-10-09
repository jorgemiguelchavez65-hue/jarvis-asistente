"""Informes de visitas médicas (salida en Markdown)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MedicalVisit:
    date: str  # AAAA-MM-DD
    doctor: str
    specialty: str
    reason: str
    notes: str = ""
    diagnosis: str = ""
    medications: list[str] = field(default_factory=list)
    follow_up: str = ""


def render_report(visit: MedicalVisit) -> str:
    lines = [
        f"# Informe de visita médica — {visit.date}",
        "",
        f"- **Médico:** {visit.doctor} ({visit.specialty})",
        f"- **Motivo:** {visit.reason}",
    ]
    if visit.diagnosis:
        lines.append(f"- **Diagnóstico:** {visit.diagnosis}")
    if visit.notes:
        lines += ["", "## Notas", "", visit.notes]
    if visit.medications:
        lines += ["", "## Medicación", ""] + [f"- {m}" for m in visit.medications]
    if visit.follow_up:
        lines += ["", "## Seguimiento", "", visit.follow_up]
    return "\n".join(lines) + "\n"
