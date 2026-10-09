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
    to_verify: list[str] = field(default_factory=list)
    consulted: list[dict] = field(default_factory=list)  # {"question","answer"} del copiloto en vivo


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
    if visit.consulted:
        lines += ["", "## Equipos y reactivos consultados", ""]
        for c in visit.consulted:
            lines.append(f"- **{c['question']}** — {c['answer']}")
    if visit.to_verify:
        lines += ["", "## Por verificar con el médico", ""] + [f"- {v}" for v in visit.to_verify]
    return "\n".join(lines) + "\n"
