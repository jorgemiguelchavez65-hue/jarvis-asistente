"""FirestoreStore contra el emulador real de Firestore.

    firebase emulators:exec --only firestore --project demo-jarvis "pytest tests/test_firestore.py"

Sin emulador (FIRESTORE_EMULATOR_HOST) estos tests se omiten.
"""
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from fakes import TOKEN, FakeClaude, FakeTranscriber

pytestmark = pytest.mark.skipif(not os.environ.get("FIRESTORE_EMULATOR_HOST"),
                                reason="requiere el emulador de Firestore")


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket, self.name = bucket, name

    @property
    def size(self):
        return len(self.bucket.objects[self.name])

    def upload_from_string(self, data, content_type=None):
        self.bucket.objects[self.name] = bytes(data)

    def download_as_bytes(self):
        return self.bucket.objects[self.name]

    def delete(self):
        del self.bucket.objects[self.name]


class FakeBucket:
    """Cloud Storage en memoria: lo mínimo que usa FirestoreStore."""

    def __init__(self):
        self.objects = {}

    def blob(self, name):
        return FakeBlob(self, name)

    def list_blobs(self, prefix=""):
        return [FakeBlob(self, n) for n in sorted(self.objects) if n.startswith(prefix)]


@pytest.fixture
def store():
    from google.cloud import firestore

    from jarvis.web.firestore_store import FirestoreStore

    db = firestore.Client(project="demo-jarvis")
    # colección única por test: los tests no se pisan entre sí
    return FirestoreStore(db, FakeBucket(), collection=f"visits_{time.time_ns()}")


def test_crud_and_list_order(store):
    a = store.create("Clínica A", "", None)
    time.sleep(1.1)  # `created` tiene resolución de segundos
    b = store.create("Clínica B", "Dra. Ruiz", "2026-01-02")
    assert [v["client"] for v in store.list()] == ["Clínica B", "Clínica A"]
    assert set(store.list()[0]) == {"id", "created", "date", "client", "status"}  # sin transcripción
    assert store.get(b["id"])["contact"] == "Dra. Ruiz"
    assert store.update(a["id"], notes="n")["notes"] == "n"
    store.delete(a["id"])
    with pytest.raises(KeyError):
        store.get(a["id"])
    with pytest.raises(KeyError):
        store.update(a["id"], notes="x")
    with pytest.raises(KeyError):
        store.get("../../etc")


def test_concurrent_questions_are_not_lost(store):
    vid = store.create("X", "", None)["id"]
    threads = [threading.Thread(target=store.append_consulted,
                                args=(vid, {"question": f"q{i}", "answer": "a", "photo": False}))
               for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(c["question"] for c in store.get(vid)["consulted"]) == sorted(f"q{i}" for i in range(12))


def test_claim_is_exclusive_under_concurrency(store):
    vid = store.create("X", "", None)["id"]
    assert store.claim(vid, 60) is False                 # 'open' no se puede tomar
    store.update(vid, status="queued")
    results = []
    threads = [threading.Thread(target=lambda: results.append(store.claim(vid, 60))) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count(True) == 1, results
    assert store.get(vid)["status"] == "processing"
    assert store.claim(vid, 60) is False                 # lo tiene otro intento
    store.update(vid, claimed_at=time.time() - 120)
    assert store.claim(vid, 60) is True                  # el intento anterior venció


def test_audio_parts_roundtrip(store, tmp_path):
    vid = store.create("X", "", None)["id"]
    store.save_part(vid, 200, 1, "webm", b"B2", 1000)
    store.save_part(vid, 200, 0, "webm", b"B1", 1000)
    store.save_part(vid, 200, 0, "webm", b"B1", 1000)   # reintento: idempotente
    store.save_part(vid, 100, 0, "webm", b"A1", 1000)
    with pytest.raises(ValueError):
        store.save_part(vid, 300, 0, "webm", b"x" * 995, 1000)
    files = store.materialize_audio(vid, tmp_path)
    assert [f.read_bytes() for f in files] == [b"A1", b"B1B2"]
    store.discard_audio(vid)
    assert store.materialize_audio(vid, tmp_path) == []


def test_whole_app_on_firestore(store, config):
    from jarvis.web.app import create_app

    class Q:  # equivale a Cloud Tasks entregando la tarea al instante
        def enqueue(self, visit_id):
            self.app_handle(visit_id)

    q = Q()
    app = create_app(config, claude=FakeClaude(), transcriber=FakeTranscriber(), store=store,
                     dispatcher=q, task_verifier=lambda r: None)
    q.app_handle = lambda vid: TestClient(app).post(f"/internal/process/{vid}")
    c = TestClient(app)
    c.headers["X-Jarvis-Token"] = TOKEN
    vid = c.post("/api/visits", json={"client": "Lab Sur", "consent": True}).json()["id"]
    c.post(f"/api/visits/{vid}/ask", json={"question": "¿Qué es un XR-200?"})
    c.put(f"/api/visits/{vid}/audio/1/0", content=b"audio", headers={"Content-Type": "audio/webm"})
    c.post(f"/api/visits/{vid}/finish", data={"notes": "nota"})
    v = c.get(f"/api/visits/{vid}").json()
    assert v["status"] == "done", v
    assert "¿Qué es un XR-200?" in v["report_md"] and "Enviar cotización" in v["report_md"]
    assert store._bucket.objects == {}                    # el audio se borró tras transcribir
