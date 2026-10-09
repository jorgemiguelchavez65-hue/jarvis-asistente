"""Flujo de Cloud Tasks: el teléfono encola, Cloud Tasks llama a /internal/process."""
import datetime
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from fakes import TOKEN, FakeClaude, FakeTranscriber
from jarvis.web.app import GIVE_UP_S, create_app
from jarvis.web.dispatch import CloudTasksDispatcher
from jarvis.web.store import LocalStore


class Queue:
    def __init__(self):
        self.ids = []

    def enqueue(self, visit_id):
        self.ids.append(visit_id)


class Flaky(FakeClaude):
    def __init__(self, failures):
        super().__init__()
        self.failures = failures

    def create(self, **kw):
        if kw.get("tools") and self.failures:
            self.failures -= 1
            raise RuntimeError("API caída")
        return super().create(**kw)


def build(config, claude=None, max_attempts=3, verify=None):
    q, store = Queue(), LocalStore(config.data_dir)
    app = create_app(config, claude=claude or FakeClaude(), transcriber=FakeTranscriber(), store=store,
                     dispatcher=q, task_verifier=verify or (lambda request: None),
                     tasks_max_attempts=max_attempts)
    c = TestClient(app)
    c.headers["X-Jarvis-Token"] = TOKEN
    return c, q, store


def start(c, q):
    vid = c.post("/api/visits", json={"client": "Lab Sur", "consent": True}).json()["id"]
    c.put(f"/api/visits/{vid}/audio/1/0", content=b"audio", headers={"Content-Type": "audio/webm"})
    assert c.post(f"/api/visits/{vid}/finish").json()["status"] == "queued"
    assert q.ids == [vid]
    return vid


def task(c, vid, retry=0):
    return c.post(f"/internal/process/{vid}", headers={"X-CloudTasks-TaskRetryCount": str(retry)})


def test_finish_only_queues_then_task_processes(config):
    c, q, _ = build(config)
    vid = start(c, q)
    assert c.get(f"/api/visits/{vid}").json()["status"] == "queued"   # nada se procesó en la petición
    assert task(c, vid).status_code == 200
    assert c.get(f"/api/visits/{vid}").json()["status"] == "done"


def test_failure_asks_cloud_tasks_to_retry_then_succeeds(config):
    c, q, _ = build(config, claude=Flaky(1))
    vid = start(c, q)
    assert task(c, vid, retry=0).status_code == 500                   # Cloud Tasks reintentará
    v = c.get(f"/api/visits/{vid}").json()
    assert v["status"] == "queued" and "Reintentando" in v["error"]
    assert task(c, vid, retry=1).status_code == 200
    v = c.get(f"/api/visits/{vid}").json()
    assert v["status"] == "done" and v["error"] == ""


def test_last_attempt_marks_error_and_stops_retries(config):
    c, q, _ = build(config, claude=Flaky(99), max_attempts=3)
    vid = start(c, q)
    assert task(c, vid, retry=0).status_code == 500
    assert task(c, vid, retry=1).status_code == 500
    assert task(c, vid, retry=2).status_code == 200                   # 2xx: que no se reintente más
    v = c.get(f"/api/visits/{vid}").json()
    assert v["status"] == "error" and "API caída" in v["error"]
    assert v["transcript"]                                            # la transcripción no se pierde


def test_duplicate_task_does_not_process_twice(config):
    claude = FakeClaude()
    c, q, _ = build(config, claude=claude)
    vid = start(c, q)
    task(c, vid)
    calls = len(claude.calls)
    assert task(c, vid).json() == {"processed": False}
    assert len(claude.calls) == calls


def test_task_while_other_attempt_running_is_retried_later(config):
    c, q, store = build(config)
    vid = start(c, q)
    assert store.claim(vid, 3600)                                     # otro intento lo tiene
    assert task(c, vid).status_code == 500
    store.update(vid, claimed_at=time.time() - 3 * 3600)              # ese intento murió hace horas
    assert task(c, vid).status_code == 200
    assert c.get(f"/api/visits/{vid}").json()["status"] == "done"


def test_stuck_visit_expires_into_error(config):
    c, q, store = build(config)
    vid = start(c, q)
    store.update(vid)  # refresca updated_at
    v = store.get(vid)
    v["updated_at"] = time.time() - GIVE_UP_S - 10
    store._save(v)
    got = c.get(f"/api/visits/{vid}").json()
    assert got["status"] == "error" and "Reintentar" in got["error"]
    assert c.post(f"/api/visits/{vid}/finish").status_code == 200     # reintentar vuelve a encolar


def test_internal_route_requires_valid_task_auth(config):
    def deny(request):
        raise HTTPException(401, "No autorizado")

    c, q, _ = build(config, verify=deny)
    vid = start(c, q)
    anon = TestClient(c.app)
    assert anon.post(f"/internal/process/{vid}").status_code == 401
    assert c.get(f"/api/visits/{vid}").json()["status"] == "queued"


def test_internal_route_absent_without_verifier(config):
    app = create_app(config, claude=FakeClaude(), transcriber=FakeTranscriber(), background=False)
    assert TestClient(app).post("/internal/process/abcdefgh12").status_code in (404, 405)


def test_deleted_visit_task_is_dropped_not_retried(config):
    c, q, _ = build(config)
    vid = start(c, q)
    c.delete(f"/api/visits/{vid}")
    assert task(c, vid).status_code == 200


def test_enqueue_failure_is_reported_to_the_user(config):
    class Broken:
        def enqueue(self, visit_id):
            raise RuntimeError("cola no disponible")

    c = TestClient(create_app(config, claude=FakeClaude(), transcriber=FakeTranscriber(),
                              store=LocalStore(config.data_dir), dispatcher=Broken()))
    c.headers["X-Jarvis-Token"] = TOKEN
    vid = c.post("/api/visits", json={"client": "X", "consent": True}).json()["id"]
    c.post(f"/api/visits/{vid}/finish")
    v = c.get(f"/api/visits/{vid}").json()
    assert v["status"] == "error" and "cola no disponible" in v["error"]


def test_cloud_tasks_dispatcher_builds_authenticated_request():
    class FakeTasks:
        def queue_path(self, p, l, q):
            return f"projects/{p}/locations/{l}/queues/{q}"

        def create_task(self, request):
            self.request = request

    ft = FakeTasks()
    CloudTasksDispatcher(ft, project="p", location="us-central1", queue="jarvis-process",
                         service_url="https://jarvis-abc.run.app/", service_account="sa@p.iam.gserviceaccount.com"
                         ).enqueue("visita123")
    r = ft.request
    assert r["parent"] == "projects/p/locations/us-central1/queues/jarvis-process"
    http = r["task"]["http_request"]
    assert http["url"] == "https://jarvis-abc.run.app/internal/process/visita123"
    assert http["oidc_token"] == {"service_account_email": "sa@p.iam.gserviceaccount.com",
                                  "audience": "https://jarvis-abc.run.app"}
    assert r["task"]["dispatch_deadline"] <= datetime.timedelta(minutes=30)


def test_gcp_backend_requires_its_settings(monkeypatch):
    from jarvis.web.main import build_app
    monkeypatch.setenv("JARVIS_BACKEND", "gcp")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("JARVIS_ACCESS_TOKEN", "t" * 24)
    for k in ("GOOGLE_CLOUD_PROJECT", "JARVIS_AUDIO_BUCKET", "JARVIS_SERVICE_URL", "JARVIS_TASKS_SA"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
        build_app()
