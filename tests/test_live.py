import json
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace as NS

from jarvis.ai.live_assistant import LiveAssistant
from jarvis.reports import MedicalVisit, render_report
from jarvis.server import make_server


class FakeClient:
    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return NS(content=[NS(type="text", text="Es un analizador de hematología.")])


def test_assistant_sends_image_and_keeps_text_history():
    fake = FakeClient()
    a = LiveAssistant(fake, "m")
    a.ask("¿Qué es esto?", image_b64="AAAA")
    a.ask("¿Y para qué sirve?")
    first = fake.calls[0]["messages"][-1]["content"]
    assert first[0]["type"] == "image"
    assert len(fake.calls[1]["messages"]) == 3  # pregunta1, respuesta1, pregunta2 (sin foto)
    assert a.log[0]["photo"] and not a.log[1]["photo"]


def test_server_requires_token_and_logs(tmp_path):
    a = LiveAssistant(FakeClient(), "m")
    srv = make_server(a, "secreto", tmp_path / "log.json", port=0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/?t=malo")
            assert False, "debió rechazar"
        except urllib.error.HTTPError as e:
            assert e.code == 403
        req = urllib.request.Request(f"http://127.0.0.1:{port}/ask?t=secreto",
                                     data=json.dumps({"question": "¿Qué es un HbA1c?"}).encode())
        assert "analizador" in json.load(urllib.request.urlopen(req))["answer"]
        assert json.loads((tmp_path / "log.json").read_text())[0]["question"] == "¿Qué es un HbA1c?"
    finally:
        srv.shutdown()


def test_report_lists_consulted():
    md = render_report(MedicalVisit(date="d", doctor="x", specialty="y", reason="z",
                                    consulted=[{"question": "HbA1c", "answer": "Azúcar promedio."}]))
    assert "## Equipos y reactivos consultados" in md and "Azúcar promedio." in md
