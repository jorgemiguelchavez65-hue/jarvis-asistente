from types import SimpleNamespace as NS

TOKEN = "t" * 24


class FakeClaude:
    """Imita anthropic.Anthropic: texto para consultas, tool_use para el informe."""

    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if kw.get("tools"):
            return NS(content=[NS(type="tool_use", input={
                "summary": "Se presentó el analizador XR-200.",
                "topics": [{"item": "XR-200", "detail": "Interesado en el contrato de servicio"}],
                "commitments": [{"what": "Enviar cotización", "who": "yo", "when": "viernes"}],
                "to_verify": ["Referencia del reactivo mal transcrita"],
            })])
        return NS(content=[NS(type="text", text="Es un analizador de hematología.")])


class FakeTranscriber:
    def __init__(self, text="El doctor pidió una cotización del XR-200."):
        self.text, self.seen = text, []

    def transcribe(self, path):
        self.seen.append(path.name)
        return self.text
