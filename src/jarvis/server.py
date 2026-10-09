"""Servidor web mínimo para usar el copiloto desde el teléfono (mismo Wi-Fi)."""
from __future__ import annotations

import hmac
import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from jarvis.storage import JsonStore

MAX_BODY = 8 * 1024 * 1024

PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Jarvis</title>
<style>
body{font-family:system-ui;margin:0;display:flex;flex-direction:column;height:100dvh;background:#f5f5f7}
#log{flex:1;overflow:auto;padding:12px}
.q{background:#0a84ff;color:#fff;margin:8px 0 8px 20%;padding:8px 12px;border-radius:14px}
.a{background:#fff;margin:8px 20% 8px 0;padding:8px 12px;border-radius:14px;white-space:pre-wrap}
form{display:flex;gap:6px;padding:8px;background:#fff;border-top:1px solid #ddd}
input[type=text]{flex:1;font-size:16px;padding:10px;border:1px solid #ccc;border-radius:10px}
button,label{font-size:16px;padding:10px 12px;border-radius:10px;border:0;background:#0a84ff;color:#fff}
label{background:#555}
</style></head><body>
<div id="log"></div>
<form id="f">
<label>📷<input id="p" type="file" accept="image/*" capture="environment" hidden></label>
<input id="q" type="text" placeholder="Pregunta sobre un equipo o reactivo…" autocomplete="off">
<button>Enviar</button></form>
<script>
const T=new URLSearchParams(location.search).get('t'),log=document.getElementById('log');
const add=(c,t)=>{const d=document.createElement('div');d.className=c;d.textContent=t;log.appendChild(d);log.scrollTop=1e9;return d};
function shrink(file){return new Promise(res=>{const i=new Image();i.onload=()=>{const s=Math.min(1,1280/Math.max(i.width,i.height)),c=document.createElement('canvas');
c.width=i.width*s;c.height=i.height*s;c.getContext('2d').drawImage(i,0,0,c.width,c.height);res(c.toDataURL('image/jpeg',.8).split(',')[1])};i.src=URL.createObjectURL(file)})}
document.getElementById('f').onsubmit=async e=>{e.preventDefault();
const q=document.getElementById('q'),p=document.getElementById('p'),file=p.files[0];
if(!q.value&&!file)return;add('q',(file?'📷 ':'')+q.value);const w=add('a','…');
const body={question:q.value};if(file)body.image=await shrink(file);q.value='';p.value='';
try{const r=await fetch('/ask?t='+T,{method:'POST',body:JSON.stringify(body)});
const j=await r.json();w.textContent=j.answer||j.error||'Error'}catch(x){w.textContent='Sin conexión con Jarvis'}};
</script></body></html>"""


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no envía nada; solo elige la interfaz
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def make_server(assistant, token: str, log_path: Path, host: str = "127.0.0.1",
                port: int = 8765) -> ThreadingHTTPServer:
    store = JsonStore(log_path)

    class Handler(BaseHTTPRequestHandler):
        def _authorized(self) -> bool:
            given = parse_qs(urlparse(self.path).query).get("t", [""])[0]
            return hmac.compare_digest(given, token)

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: dict) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

        def do_GET(self):  # noqa: N802
            if urlparse(self.path).path != "/" or not self._authorized():
                return self._json(403, {"error": "No autorizado"})
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")

        def do_POST(self):  # noqa: N802
            if urlparse(self.path).path != "/ask" or not self._authorized():
                return self._json(403, {"error": "No autorizado"})
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BODY:
                return self._json(413, {"error": "Foto demasiado grande"})
            try:
                data = json.loads(self.rfile.read(length))
                answer = assistant.ask(str(data.get("question", "")).strip(), data.get("image"))
            except Exception as exc:  # el teléfono debe ver el fallo, no una conexión cortada
                return self._json(500, {"error": f"Jarvis no pudo responder: {exc}"})
            store.save(assistant.log)
            self._json(200, {"answer": answer})

        def log_message(self, *args):  # sin ruido: las preguntas no deben ir a la consola
            pass

    return ThreadingHTTPServer((host, port), Handler)
