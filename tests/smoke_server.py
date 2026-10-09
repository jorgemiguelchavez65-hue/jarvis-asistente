"""Arranca el servidor REAL (Postgres + SDK de Anthropic + transcriptor por API) contra servidores
falsos por HTTP, y recorre una visita completa, incluido un reinicio a mitad del trabajo.

    DATABASE_URL=postgresql://usuario@localhost/base python tests/smoke_server.py
"""
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

TOKEN = "smoke-token-0123456789"
seen = {"claude": [], "stt": []}
STT_DELAY = {"s": 0.0}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path.startswith("/v1/messages"):
            req = json.loads(body)
            seen["claude"].append(req)
            if req.get("tools"):
                content = [{"type": "tool_use", "id": "toolu_1", "name": "registrar_visita", "input": {
                    "summary": "Se habló del analizador XR-200.",
                    "topics": [{"item": "XR-200", "detail": "Pidió cotización"}],
                    "commitments": [{"what": "Enviar cotización", "who": "yo", "when": "viernes"}]}}]
                stop = "tool_use"
            else:
                content, stop = [{"type": "text", "text": "Es un analizador de hematología."}], "end_turn"
            out = {"id": "msg_1", "type": "message", "role": "assistant", "model": "m", "content": content,
                   "stop_reason": stop, "stop_sequence": None,
                   "usage": {"input_tokens": 1, "output_tokens": 1}}
            data, ctype = json.dumps(out).encode(), "application/json"
        elif self.path.startswith("/v1/audio/transcriptions"):
            seen["stt"].append({"auth": self.headers.get("Authorization"), "len": len(body),
                                "head": body[:400]})
            time.sleep(STT_DELAY["s"])
            data, ctype = "El doctor pidió una cotización del XR-200.".encode(), "text/plain"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=fake.serve_forever, daemon=True).start()
FAKE = f"http://127.0.0.1:{fake.server_address[1]}"
APP = "http://127.0.0.1:18080"
H = {"X-Jarvis-Token": TOKEN}
env = dict(os.environ, JARVIS_BACKEND="postgres", DATABASE_URL=os.environ["DATABASE_URL"],
           JARVIS_STT="api", JARVIS_STT_BASE_URL=FAKE + "/v1", JARVIS_STT_API_KEY="stt-key",
           JARVIS_STT_MODEL="whisper-x", ANTHROPIC_API_KEY="k", ANTHROPIC_BASE_URL=FAKE,
           JARVIS_ACCESS_TOKEN=TOKEN, PORT="18080", HOST="127.0.0.1", NO_PROXY="127.0.0.1")


def start():
    p = subprocess.Popen([sys.executable, "-m", "jarvis.web.main"], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(60):
        try:
            if httpx.get(APP + "/healthz", timeout=1).status_code == 200:
                return p
        except httpx.HTTPError:
            time.sleep(0.5)
    p.kill()
    raise SystemExit("el servidor no arrancó:\n" + p.stdout.read())


def wait_status(vid, want, secs=30):
    for _ in range(secs * 4):
        v = httpx.get(f"{APP}/api/visits/{vid}", headers=H).json()
        if v["status"] in want:
            return v
        time.sleep(0.25)
    raise SystemExit(f"timeout esperando {want}; estado: {v['status']} {v.get('error')}")


proc = start()
try:
    assert httpx.get(APP + "/api/visits").status_code == 401
    vid = httpx.post(APP + "/api/visits", headers=H, json={"client": "Laboratorio Sur", "consent": True}).json()["id"]
    a = httpx.post(f"{APP}/api/visits/{vid}/ask", headers=H, json={"question": "¿Qué es un XR-200?", "image": "QUJD"})
    assert a.status_code == 200 and "hematología" in a.json()["answer"], a.text
    img = seen["claude"][0]["messages"][-1]["content"][0]
    assert img["type"] == "image" and img["source"]["data"] == "QUJD", "el SDK no mandó la foto como se esperaba"
    for seq in range(3):
        r = httpx.put(f"{APP}/api/visits/{vid}/audio/1/{seq}", headers={**H, "Content-Type": "audio/webm;codecs=opus"},
                      content=b"\x1a\x45\xdf\xa3" + bytes([seq]) * 5000)
        assert r.status_code == 200, r.text

    # --- escenario Render: la instancia muere a mitad de la transcripción ---
    STT_DELAY["s"] = 4.0
    assert httpx.post(f"{APP}/api/visits/{vid}/finish", headers=H, data={"notes": "pidió precio"}).status_code == 200
    wait_status(vid, {"processing"})
    time.sleep(1.0)
    proc.kill(); proc.wait()
    print("servidor muerto a mitad del trabajo; reiniciando…")
    STT_DELAY["s"] = 0.0
    proc = start()
    # recover_pending solo retoma lo procesado hace más de 5 min: aquí llevaba segundos, así que se
    # deja quieto a propósito. Se simula el paso del tiempo envejeciendo la visita.
    import psycopg
    with psycopg.connect(env["DATABASE_URL"], autocommit=True) as c:
        c.execute("UPDATE visits SET data = data || jsonb_build_object('updated_at', %s::float) WHERE id=%s",
                  (time.time() - 3600, vid))
    proc.kill(); proc.wait(); proc = start()      # nuevo arranque: ahora sí debe retomarlo
    v = wait_status(vid, {"done", "error"}, 40)
    assert v["status"] == "done", v
    md = v["report_md"]
    assert "Laboratorio Sur" in md and "Enviar cotización" in md and "¿Qué es un XR-200?" in md, md
    assert v["transcript"].startswith("El doctor"), v["transcript"]
    stt = seen["stt"][-1]
    assert stt["auth"] == "Bearer stt-key" and b"whisper-x" in stt["head"], stt
    assert stt["len"] >= 3 * 5000, "el audio unido no llegó completo al servicio de voz"
    report_req = [r for r in seen["claude"] if r.get("tools")][-1]
    assert report_req["tool_choice"] == {"type": "tool", "name": "registrar_visita"}
    prompt = report_req["messages"][0]["content"]
    assert "pidió precio" in prompt and "XR-200" in prompt and "Laboratorio Sur" in prompt
    audio_left = psycopg.connect(env["DATABASE_URL"]).execute("SELECT count(*) FROM audio_parts").fetchone()[0]
    assert audio_left == 0, f"quedaron {audio_left} trozos de audio en la base"
    print(md)
    print("SMOKE OK — transcripciones solicitadas al servicio de voz:", len(seen["stt"]))
finally:
    proc.kill()
