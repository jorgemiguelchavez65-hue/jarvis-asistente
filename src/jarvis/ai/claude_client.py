"""Cliente de la API de Claude (esqueleto para la fase 2)."""
from __future__ import annotations

from jarvis.config import Config


class ClaudeNotConfigured(RuntimeError):
    pass


class ClaudeClient:
    def __init__(self, config: Config):
        if not config.anthropic_api_key:
            raise ClaudeNotConfigured(
                "Falta ANTHROPIC_API_KEY. Copia .env.example a .env y complétala."
            )
        try:
            import anthropic
        except ImportError as exc:
            raise ClaudeNotConfigured(
                "Instala el extra de IA: pip install -e '.[ai]'"
            ) from exc
        self._client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self._model = config.model

    def visit_from_transcript(self, transcript: str, date: str):
        from jarvis.ai.visit_extractor import extract_visit

        return extract_visit(self._client, self._model, transcript, date)

    def ask(self, question: str, system: str = "Eres Jarvis, un asistente personal útil y conciso.") -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": question}],
        )
        return "".join(b.text for b in response.content if b.type == "text")
