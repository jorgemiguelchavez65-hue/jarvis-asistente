"""PostgresStore contra un Postgres real.

    TEST_DATABASE_URL=postgresql://usuario@localhost/base pytest tests/test_postgres.py

Sin TEST_DATABASE_URL estos tests se omiten. Crean y borran sus propias tablas en esa base.
"""
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from fakes import TOKEN, FakeClaude, FakeTranscriber

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),
                                reason="requiere TEST_DATABASE_URL")


@pytest.fixture
def store():
    import psycopg

    from jarvis.web.pg_store import PostgresStore

    url = os.environ["TEST_DATABASE_URL"]
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("DROP TABLE IF EXISTS visits, audio_parts")
    s = PostgresStore(url)
    yield s
    s._pool.close()


def test_crud_and_list_order(store):
    a = store.create("Clínica A", "", None)
    time.sleep(1.1)  # `created` tiene resolución de segundos
    b = store.create("Clínica B", "Dra. Ruiz", "2026-01-02")
    assert [v["client"] for v in store.list()] == ["Clínica B", "Clínica A"]
    assert set(store.list()[0]) == {"id", "created", "date", "client", "status"}  # sin transcripción
    assert store.get(b["id"])["contact"] == "Dra. Ruiz"
    assert store.update(a["id"], notes="ñandú ✓")["notes"] == "ñandú ✓"
    assert store.get(a["id"])["client"] == "Clínica A"          # update mezcla, no reemplaza
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
               for i in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(c["question"] for c in store.get(vid)["consulted"]) == sorted(f"q{i}" for i in range(20))


def test_claim_is_exclusive_under_concurrency(store):
    vid = store.create("X", "", None)["id"]
    assert store.claim(vid, 60) is False                 # 'open' no se puede tomar
    store.update(vid, status="queued")
    results = []
    threads = [threading.Thread(target=lambda: results.append(store.claim(vid, 60))) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count(True) == 1, results
    assert store.get(vid)["status"] == "processing"
    assert store.claim(vid, 60) is False                 # lo tiene otro intento
    store.update(vid, claimed_at=time.time() - 120)
    assert store.claim(vid, 60) is True                  # el intento anterior venció
    store.update(vid, status="done")
    assert store.claim(vid, 0) is False


def test_audio_parts_roundtrip_limit_and_idempotence(store, tmp_path):
    vid = store.create("X", "", None)["id"]
    store.save_part(vid, 200, 1, "webm", b"B2", 1000)
    store.save_part(vid, 200, 0, "webm", b"B1", 1000)
    store.save_part(vid, 200, 0, "webm", b"B1", 1000)    # reintento: idempotente, no cuenta doble
    store.save_part(vid, 100, 0, "webm", b"A1", 1000)
    store.save_part(vid, 300, 0, "webm", b"x" * 994, 1000)
    with pytest.raises(ValueError):
        store.save_part(vid, 300, 1, "webm", b"x", 1000)  # 1000 exactos ya usados
    store.save_part(vid, 300, 0, "webm", b"y" * 990, 1000)  # reemplazar un trozo libera su espacio
    files = store.materialize_audio(vid, tmp_path)
    assert [f.read_bytes()[:2] for f in files] == [b"A1", b"B1B2"[:2], b"yy"]
    assert files[1].read_bytes() == b"B1B2" and files[0].name == "000.webm"
    store.discard_audio(vid)
    assert store.materialize_audio(vid, tmp_path) == []


def test_state_survives_a_new_connection_pool(store):
    """Lo que hace falta en Render: reiniciar la instancia no pierde nada."""
    from jarvis.web.pg_store import PostgresStore

    vid = store.create("Lab", "", None)["id"]
    store.save_part(vid, 1, 0, "webm", b"audio", 1000)
    again = PostgresStore(os.environ["TEST_DATABASE_URL"])
    try:
        assert again.get(vid)["client"] == "Lab"
        assert again.list()[0]["id"] == vid
    finally:
        again._pool.close()


def test_whole_app_on_postgres(store, config):
    from jarvis.web.app import create_app

    c = TestClient(create_app(config, claude=FakeClaude(), transcriber=FakeTranscriber(), store=store,
                              background=False))
    c.headers["X-Jarvis-Token"] = TOKEN
    vid = c.post("/api/visits", json={"client": "Lab Sur", "consent": True}).json()["id"]
    c.post(f"/api/visits/{vid}/ask", json={"question": "¿Qué es un XR-200?"})
    c.put(f"/api/visits/{vid}/audio/1/0", content=b"audio", headers={"Content-Type": "audio/webm"})
    c.post(f"/api/visits/{vid}/finish", data={"notes": "nota"})
    v = c.get(f"/api/visits/{vid}").json()
    assert v["status"] == "done", v
    assert "¿Qué es un XR-200?" in v["report_md"] and "Enviar cotización" in v["report_md"]
    assert store.materialize_audio(vid, config.data_dir) == []     # audio borrado tras transcribir
    assert [x["id"] for x in c.get("/api/visits").json()] == [vid]
    c.delete(f"/api/visits/{vid}")
    assert c.get("/api/visits").json() == []
