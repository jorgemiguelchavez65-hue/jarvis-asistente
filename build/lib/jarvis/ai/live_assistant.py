"""Consultas en vivo durante la visita: preguntas (con foto opcional) sobre equipos y reactivos."""
from __future__ import annotations

from typing import Any

SYSTEM = """Eres Jarvis, copiloto de un profesional que visita médicos y laboratorios por trabajo.
Te pregunta, en el momento, por equipos, reactivos, pruebas, normas o términos que no conoce
(a veces con una foto de la etiqueta o del aparato). Está en plena conversación: sé breve.
- Español, 3 a 6 líneas: qué es, para qué se usa y qué conviene saber o preguntar al cliente.
- Si identificas algo por una foto, di qué lees exactamente; si no es legible o no estás seguro, dilo.
- No inventes especificaciones, precios ni referencias de catálogo: si no las sabes, dilo.
- Si te preguntan por una decisión clínica, no la tomes: sugiere la pregunta para el profesional."""

MAX_TURNS = 10  # pares pregunta/respuesta que se reenvían como contexto


def ask_live(client: Any, model: str, history: list[dict], question: str,
             image_b64: str | None = None, media_type: str = "image/jpeg") -> str:
    """`history` son las consultas previas de esta visita: [{"question","answer"}, ...]."""
    messages: list[dict] = []
    for h in history[-MAX_TURNS:]:
        messages += [{"role": "user", "content": h["question"]},
                     {"role": "assistant", "content": h["answer"]}]
    content: list[dict] = []
    if image_b64:
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": image_b64}})
    content.append({"type": "text", "text": question or "¿Qué es esto?"})
    messages.append({"role": "user", "content": content})
    response = client.messages.create(model=model, max_tokens=600, system=SYSTEM, messages=messages)
    return "".join(b.text for b in response.content if b.type == "text").strip()
