"""Informe de visita de trabajo a un médico o laboratorio (salida en Markdown)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class FieldVisit:
    date: str  # AAAA-MM-DD
    client: str  # institución, consultorio o laboratorio
    contact: str = ""  # persona con quien se habló
    summary: str = ""
    topics: list[dict] = field(default_factory=list)  # {"item": equipo/reactivo, "detail": ...}
    needs: list[str] = field(default_factory=list)
    commitments: list[dict] = field(default_factory=list)  # {"what", "who", "when"}
    next_steps: list[str] = field(default_factory=list)
    to_verify: list[str] = field(default_factory=list)
    consulted: list[dict] = field(default_factory=list)  # {"question", "answer"} del copiloto

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FieldVisit":
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})


def render_report(v: FieldVisit) -> str:
    lines = [f"# Informe de visita — {v.client}", "", f"- **Fecha:** {v.date}"]
    if v.contact:
        lines.append(f"- **Contacto:** {v.contact}")
    if v.summary:
        lines += ["", "## Resumen", "", v.summary]
    if v.topics:
        lines += ["", "## Equipos y reactivos tratados", ""]
        lines += [f"- **{t.get('item', '')}** — {t.get('detail', '')}" for t in v.topics]
    if v.needs:
        lines += ["", "## Necesidades detectadas", ""] + [f"- {n}" for n in v.needs]
    if v.commitments:
        lines += ["", "## Compromisos", ""]
        for c in v.commitments:
            who = f" ({c['who']})" if c.get("who") else ""
            when = f" — {c['when']}" if c.get("when") else ""
            lines.append(f"- {c.get('what', '')}{who}{when}")
    if v.next_steps:
        lines += ["", "## Próximos pasos", ""] + [f"- {s}" for s in v.next_steps]
    if v.consulted:
        lines += ["", "## Consultas hechas durante la visita", ""]
        lines += [f"- **{c['question']}** — {c['answer']}" for c in v.consulted]
    if v.to_verify:
        lines += ["", "## Por verificar", ""] + [f"- {x}" for x in v.to_verify]
    return "\n".join(lines) + "\n"
