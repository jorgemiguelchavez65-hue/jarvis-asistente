"""Consultas en vivo durante la visita: preguntas (con foto opcional) sobre equipos y reactivos."""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

SYSTEM = """Eres Jarvis, copiloto de un paciente durante una visita médica.
El paciente te pregunta, en el momento, por equipos, reactivos, pruebas o términos que no conoce
(a veces con una foto de la etiqueta o del aparato).
- Responde en español, en 3 a 6 líneas: qué es, para qué se usa y qué le puede interesar saber.
- Si identificas algo por una foto, di qué lees exactamente en ella; si no es legible o no estás seguro, dilo.
- No des diagnósticos ni cambies indicaciones médicas. Si la pregunta es clínica, sugiere
  formularla al médico y propón la pregunta concreta."""

MAX_TURNS = 10  # pares pregunta/respuesta que se reenvían como contexto


class LiveAssistant:
    def __init__(self, client: Any, model: str):
        self._client = client
        self._model = model
        self._history: list[dict] = []
        self._lock = threading.Lock()
        self.log: list[dict] = []

    def ask(self, question: str, image_b64: str | None = None, media_type: str = "image/jpeg") -> str:
        content: list[dict] = []
        if image_b64:
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": image_b64}})
        content.append({"type": "text", "text": question or "¿Qué es esto?"})
        with self._lock:
            messages = self._history[-2 * MAX_TURNS:] + [{"role": "user", "content": content}]
            response = self._client.messages.create(
                model=self._model, max_tokens=600, system=SYSTEM, messages=messages
            )
            answer = "".join(b.text for b in response.content if b.type == "text").strip()
            # En el historial se guarda solo el texto: las fotos pesan y no hace falta reenviarlas.
            self._history += [{"role": "user", "content": question or "(foto)"},
                              {"role": "assistant", "content": answer}]
            self.log.append({"time": datetime.now().strftime("%H:%M"),
                             "question": question or "(foto)", "answer": answer,
                             "photo": bool(image_b64)})
        return answer
