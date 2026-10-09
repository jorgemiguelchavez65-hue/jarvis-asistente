from types import SimpleNamespace as NS

from jarvis.ai.visit_extractor import extract_visit
from jarvis.reports import render_report


class FakeClient:
    def __init__(self, payload):
        self.calls = []
        self.messages = self
        self._payload = payload

    def create(self, **kw):
        self.calls.append(kw)
        return NS(content=[NS(type="tool_use", input=self._payload)])


def test_extract_visit_builds_report():
    fake = FakeClient({
        "reason": "Dolor de cabeza", "notes": "Tres días de dolor.",
        "medications": ["Ibuprofeno 400 mg cada 8 h"],
        "to_verify": ["Dosis de ibuprofeno poco clara"],
    })
    visit = extract_visit(fake, "m", "…transcripción…", "2026-01-01")
    assert fake.calls[0]["tool_choice"]["name"] == "registrar_visita"
    assert visit.doctor == "No identificado"
    md = render_report(visit)
    assert "Ibuprofeno" in md and "Por verificar" in md
