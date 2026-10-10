"""Acceso a la API de Claude."""
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
            raise ClaudeNotConfigured("Instala el extra de IA: pip install -e '.[ai]'") from exc
        self.raw = anthropic.Anthropic(api_key=config.anthropic_api_key, timeout=120.0)
        self.model = config.model

    def ask(self, question: str, system: str = "Eres Jarvis, un asistente personal útil y conciso.") -> str:
        response = self.raw.messages.create(
            model=self.model, max_tokens=1024, system=system,
            messages=[{"role": "user", "content": question}],
        )
        return "".join(b.text for b in response.content if b.type == "text")
