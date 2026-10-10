"""Sobrevivir a reinicios y a que la instancia se duerma (plan gratis de Render)."""
import time

import pytest
from fastapi.testclient import TestClient

from fakes import TOKEN, FakeClaude, FakeTranscriber
from jarvis.web.app import GIVE_UP_S, create_app
from jarvis.web.store import LocalStore


class Queue:
    def __init__(self):
        self.ids = []

    def enqueue(self, visit_id):
        self.ids.append(visit_id)


def build(config, claude=None):
    q, store = Queue(), LocalStore(config.data_dir)
    app = create_app(config, claude=claude or FakeClaude(), transcriber=FakeTranscriber(),
                     store=store, dispatcher=q)
    c = TestClient(app)
    c.headers["X-Jarvis-Token"] = TOKEN
    return c, q, store, app


def start(c):
    vid = c.post("/api/visits", json={"client": "Lab Sur", "consent": True}).json()["id"]
    c.put(f"/api/visits/{vid}/audio/1/0", content=b"audio", headers={"Content-Type": "audio/webm"})
    c.post(f"/api/visits/{vid}/finish")
    return vid


def test_healthz_is_public_and_touches_nothing(config):
    c, *_ = build(config)
    anon = TestClient(c.app)
    assert anon.get("/healthz").json() == {"ok": True}
    assert anon.get("/api/visits").status_code == 401


def test_recover_requeues_queued_and_stale_processing_only(config):
    c, q, store, app = build(config)
    queued = start(c)                                              # quedó en cola al dormirse
    stale = start(c)
    store.update(stale, status="processing")
    v = store.get(stale); v["updated_at"] = time.time() - 3600; store._save(v)   # murió hace una hora
    fresh = start(c)
    store.update(fresh, status="processing")                      # otra instancia lo está haciendo
    done = start(c)
    store.update(done, status="done")
    q.ids.clear()
    assert app.state.recover_pending() == 2
    assert sorted(q.ids) == sorted([queued, stale])
    assert store.get(stale)["status"] == "queued"
    assert store.get(fresh)["status"] == "processing"
    assert store.get(done)["status"] == "done"


def test_recovered_visit_actually_completes(config):
    c = TestClient(create_app(config, claude=FakeClaude(), transcriber=FakeTranscriber(),
                              background=False))
    c.headers["X-Jarvis-Token"] = TOKEN
    store = LocalStore(config.data_dir)
    vid = c.post("/api/visits", json={"client": "X", "consent": True}).json()["id"]
    c.put(f"/api/visits/{vid}/audio/1/0", content=b"a", headers={"Content-Type": "audio/webm"})
    store.update(vid, status="queued")                            # se reinició tras encolar
    app2 = create_app(config, claude=FakeClaude(), transcriber=FakeTranscriber(), background=False)
    assert app2.state.recover_pending() == 1
    assert store.get(vid)["status"] == "done"


def test_duplicate_processing_is_skipped(config):
    claude = FakeClaude()
    c = TestClient(create_app(config, claude=claude, transcriber=FakeTranscriber(), background=False))
    c.headers["X-Jarvis-Token"] = TOKEN
    vid = start(c)
    calls = len(claude.calls)
    store = LocalStore(config.data_dir)
    assert store.claim(vid, 60) is False                           # ya está hecha: no se toma de nuevo
    assert len(claude.calls) == calls


def test_claim_blocks_second_taker_until_stale(config):
    store = LocalStore(config.data_dir)
    vid = store.create("X", "", None)["id"]
    assert store.claim(vid, 60) is False                           # 'open': no se puede tomar
    store.update(vid, status="queued")
    assert store.claim(vid, 60) is True
    assert store.claim(vid, 60) is False
    store.update(vid, claimed_at=time.time() - 120)
    assert store.claim(vid, 60) is True                            # el intento anterior venció


def test_stuck_visit_expires_into_error_and_can_retry(config):
    c, q, store, _ = build(config)
    vid = start(c)
    v = store.get(vid); v["updated_at"] = time.time() - GIVE_UP_S - 10; store._save(v)
    got = c.get(f"/api/visits/{vid}").json()
    assert got["status"] == "error" and "Reintentar" in got["error"]
    assert c.post(f"/api/visits/{vid}/finish").status_code == 200


def test_enqueue_failure_is_reported_to_the_user(config):
    class Broken:
        def enqueue(self, visit_id):
            raise RuntimeError("sin hilos")

    c = TestClient(create_app(config, claude=FakeClaude(), transcriber=FakeTranscriber(),
                              store=LocalStore(config.data_dir), dispatcher=Broken()))
    c.headers["X-Jarvis-Token"] = TOKEN
    vid = c.post("/api/visits", json={"client": "X", "consent": True}).json()["id"]
    c.post(f"/api/visits/{vid}/finish")
    v = c.get(f"/api/visits/{vid}").json()
    assert v["status"] == "error" and "sin hilos" in v["error"]


def test_stt_failure_keeps_audio_for_retry(config):
    class Flaky(FakeTranscriber):
        fail = True

        def transcribe(self, path):
            if self.fail:
                self.fail = False
                raise RuntimeError("servicio de voz caído")
            return super().transcribe(path)

    c = TestClient(create_app(config, claude=FakeClaude(), transcriber=Flaky(), background=False))
    c.headers["X-Jarvis-Token"] = TOKEN
    vid = start(c)
    v = c.get(f"/api/visits/{vid}").json()
    assert v["status"] == "error" and "voz caído" in v["error"]
    assert c.post(f"/api/visits/{vid}/finish").status_code == 200   # reintento sin volver a subir audio
    v = c.get(f"/api/visits/{vid}").json()
    assert v["status"] == "done" and v["transcript"]


def test_build_app_validates_configuration(monkeypatch):
    from jarvis.web import main

    monkeypatch.setenv("JARVIS_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("JARVIS_STT", "api")
    for k in ("JARVIS_STT_BASE_URL", "JARVIS_STT_API_KEY", "JARVIS_STT_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("JARVIS_ACCESS_TOKEN", "t" * 24)
    with pytest.raises(RuntimeError, match="JARVIS_STT_BASE_URL"):
        main.build_app()
    monkeypatch.setenv("JARVIS_STT", "otra")
    with pytest.raises(RuntimeError, match="local' o 'api"):
        main.build_app()


def test_local_stt_without_whisper_fails_at_startup_with_actionable_message(monkeypatch):
    """La causa real de 'falta faster-whisper' en Render: JARVIS_STT quedó en su valor por defecto (local)."""
    import importlib.util

    from jarvis.web import main

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a, **k: None if name == "faster_whisper" else real(name, *a, **k))
    monkeypatch.delenv("JARVIS_STT", raising=False)          # sin definir => "local"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("JARVIS_ACCESS_TOKEN", "t" * 24)
    with pytest.raises(RuntimeError, match="JARVIS_STT=api") as exc:
        main.build_app()
    assert "JARVIS_STT_API_KEY" in str(exc.value)


def test_api_stt_does_not_need_whisper(monkeypatch, tmp_path):
    import importlib.util

    from jarvis.web import main

    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *a, **k: None if name == "faster_whisper" else real(name, *a, **k))
    for k, v in {"JARVIS_STT": "api", "JARVIS_STT_BASE_URL": "http://x/v1", "JARVIS_STT_API_KEY": "k",
                 "JARVIS_STT_MODEL": "m", "ANTHROPIC_API_KEY": "x", "JARVIS_ACCESS_TOKEN": "t" * 24,
                 "JARVIS_BACKEND": "local", "JARVIS_DATA_DIR": str(tmp_path)}.items():
        monkeypatch.setenv(k, v)
    assert main.build_app() is not None
