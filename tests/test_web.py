import io

from fastapi.testclient import TestClient

from jarvis.web.app import create_app
from fakes import TOKEN, FakeClaude, FakeTranscriber


def new_visit(client, **kw):
    body = {"client": "Clínica Norte", "contact": "Dra. Ruiz", "consent": True, **kw}
    return client.post("/api/visits", json=body)


def test_api_requires_token(client, config):
    anon = TestClient(client.app)
    assert anon.get("/api/visits").status_code == 401
    assert anon.get("/api/visits", headers={"Authorization": "Bearer mal"}).status_code == 401
    assert client.get("/api/visits").status_code == 200


def test_static_app_is_public_and_installable(client):
    anon = TestClient(client.app)
    assert "Jarvis" in anon.get("/").text
    assert anon.get("/manifest.webmanifest").json()["display"] == "standalone"
    assert anon.get("/sw.js").status_code == 200
    assert anon.get("/icon-192.png").headers["content-type"] == "image/png"


def test_server_refuses_weak_token(config):
    import dataclasses

    import pytest

    weak = dataclasses.replace(config, access_token="corto")
    with pytest.raises(RuntimeError):
        create_app(weak, claude=FakeClaude(), transcriber=FakeTranscriber())


def test_consent_is_required(client):
    assert new_visit(client, consent=False).status_code == 400


def test_full_flow_audio_questions_notes_report(client, config):
    vid = new_visit(client).json()["id"]
    ask = client.post(f"/api/visits/{vid}/ask", json={"question": "¿Qué es un XR-200?", "image": "AAAA"})
    assert ask.json()["answer"].startswith("Es un analizador")

    r = client.post(f"/api/visits/{vid}/finish", data={"notes": "Pidió precio"},
                    files={"audio": ("v", io.BytesIO(b"fake-audio"), "audio/webm;codecs=opus")})
    assert r.status_code == 200
    v = client.get(f"/api/visits/{vid}").json()
    assert v["status"] == "done", v["error"]
    assert v["transcript"].startswith("El doctor")
    assert "Enviar cotización" in v["report_md"]
    assert "¿Qué es un XR-200?" in v["report_md"]          # consulta en vivo incluida
    assert "Referencia del reactivo mal transcrita" in v["report_md"]
    assert list((config.data_dir / "audio").iterdir()) == []  # audio borrado tras transcribir


def test_report_prompt_includes_all_sources(client, fake_claude):
    vid = new_visit(client).json()["id"]
    client.post(f"/api/visits/{vid}/ask", json={"question": "¿HbA1c?"})
    client.post(f"/api/visits/{vid}/finish", data={"notes": "nota-clave"},
                files={"audio": ("v", io.BytesIO(b"x"), "audio/webm")})
    prompt = fake_claude.calls[-1]["messages"][0]["content"]
    assert "Clínica Norte" in prompt and "nota-clave" in prompt and "¿HbA1c?" in prompt
    assert "XR-200" in prompt  # la transcripción


def test_finish_without_audio_uses_notes_and_questions(client):
    vid = new_visit(client).json()["id"]
    client.post(f"/api/visits/{vid}/finish", data={"notes": "solo notas"})
    assert client.get(f"/api/visits/{vid}").json()["status"] == "done"


def test_bad_audio_type_and_size_rejected(client):
    vid = new_visit(client).json()["id"]
    bad = client.post(f"/api/visits/{vid}/finish", files={"audio": ("v", io.BytesIO(b"x"), "text/html")})
    assert bad.status_code == 415
    big = client.post(f"/api/visits/{vid}/finish",
                      files={"audio": ("v", io.BytesIO(b"0" * (2 * 1024 * 1024)), "audio/webm")})
    assert big.status_code == 413


def test_failure_is_reported_and_retry_reuses_transcript(config):
    class Flaky(FakeClaude):
        fail = True

        def create(self, **kw):
            if kw.get("tools") and self.fail:
                self.fail = False
                raise RuntimeError("API caída")
            return super().create(**kw)

    tr = FakeTranscriber()
    c = TestClient(create_app(config, claude=Flaky(), transcriber=tr, background=False))
    c.headers["Authorization"] = f"Bearer {TOKEN}"
    vid = new_visit(c).json()["id"]
    c.post(f"/api/visits/{vid}/finish", files={"audio": ("v", io.BytesIO(b"x"), "audio/webm")})
    v = c.get(f"/api/visits/{vid}").json()
    assert v["status"] == "error" and "API caída" in v["error"]
    assert v["transcript"]                      # la transcripción no se pierde
    c.post(f"/api/visits/{vid}/finish")         # reintento sin volver a subir audio
    assert c.get(f"/api/visits/{vid}").json()["status"] == "done"
    assert len(tr.seen) == 1                    # no se transcribió dos veces


def test_ids_cannot_escape_data_dir(client):
    assert client.get("/api/visits/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert client.delete("/api/visits/x").status_code == 404


def test_delete_removes_visit(client):
    vid = new_visit(client).json()["id"]
    assert client.delete(f"/api/visits/{vid}").status_code == 200
    assert client.get(f"/api/visits/{vid}").status_code == 404
