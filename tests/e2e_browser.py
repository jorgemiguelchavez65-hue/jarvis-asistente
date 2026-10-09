"""Prueba de extremo a extremo en Chromium con micrófono simulado (no se ejecuta con pytest).

    python tests/e2e_browser.py
"""
import dataclasses
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import uvicorn
from fakes import TOKEN, FakeClaude, FakeTranscriber
from playwright.sync_api import sync_playwright

from jarvis.config import Config
from jarvis.web.app import create_app

data = Path(tempfile.mkdtemp())
config = dataclasses.replace(Config.load(), data_dir=data, anthropic_api_key="x", model="m",
                            access_token=TOKEN, keep_audio=False, max_audio_mb=20)

class SizingTranscriber(FakeTranscriber):
    sizes = []

    def transcribe(self, path):
        if os.environ.get("KEEP_AUDIO_TO"):
            shutil.copy(path, os.environ["KEEP_AUDIO_TO"])
        self.sizes.append((path.stat().st_size, path.read_bytes()[:4]))
        return super().transcribe(path)


tr = SizingTranscriber()
app = create_app(config, claude=FakeClaude(), transcriber=tr, background=True)
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8099, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
time.sleep(1)

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=[
        "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
    ctx = b.new_context(viewport={"width": 390, "height": 800}, permissions=["microphone"])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("http://127.0.0.1:8099/")

    page.fill("#token", "mala-contrasena-xxxxxxxx"); page.click("#login-form button")
    page.wait_for_function("document.getElementById('login-err').textContent.includes('incorrecta')")
    page.fill("#token", TOKEN); page.click("#login-form button")
    page.wait_for_selector("#home:not([hidden])")

    page.fill("#n-client", "Laboratorio Central"); page.fill("#n-contact", "Dr. Paz")
    page.click("#new-form button")
    assert page.is_hidden("#visit") is False or page.locator("#n-consent").is_visible()
    page.check("#n-consent"); page.click("#new-form button")
    page.wait_for_selector("#visit:not([hidden])")

    page.click("#rec-start")
    page.wait_for_selector("#rec-stop:not([hidden])")
    page.wait_for_timeout(int(float(os.environ.get("REC_SECONDS", "3.5")) * 1000))
    # Con grabación en curso, los trozos de 10 s ya deben estar en el servidor (no al final).
    if float(os.environ.get("REC_SECONDS", "3.5")) >= 12:
        parts = [f for d in (data / "audio").iterdir() if d.is_dir() for f in d.iterdir()]
        assert len(parts) >= 1, "el audio no se está enviando mientras se graba"
        print("trozos ya en el servidor antes de terminar:", len(parts))
    page.fill("#q", "¿Qué es un XR-200?"); page.click("#ask-form button")
    page.wait_for_function("document.querySelectorAll('.msg.a').length>0 && document.querySelector('.msg.a').textContent.includes('analizador')")
    page.click("#rec-pause"); page.wait_for_timeout(300); page.click("#rec-pause")
    page.wait_for_timeout(1500)
    page.fill("#notes", "Pidió cotización")
    page.click("#finish")
    page.wait_for_selector("#report:not([hidden])")
    page.wait_for_function("document.getElementById('r-md').textContent.includes('Enviar cotización')", timeout=15000)
    text = page.inner_text("#r-md")
    print(text)
    assert "Laboratorio Central" in text and "¿Qué es un XR-200?" in text
    assert tr.seen and tr.seen[0].endswith((".webm", ".mp4")), tr.seen
    left = page.evaluate("""() => new Promise(r => { const q = indexedDB.open('jarvis'); q.onsuccess = () => {
        const g = q.result.transaction('chunks').objectStore('chunks').count(); g.onsuccess = () => r(g.result) } })""")
    assert left == 0, f"quedaron {left} trozos de audio locales tras enviar"
    # el service worker se registra y la app abre sin red tras la primera carga
    page.wait_for_function("navigator.serviceWorker.ready.then(() => true)")
    ctx.set_offline(True)
    page.reload()
    page.wait_for_selector("#net:not([hidden])")
    ctx.set_offline(False)
    assert not errors, errors
    b.close()
size, magic = tr.sizes[0]
assert size > 10_000 and magic == b"\x1a\x45\xdf\xa3", tr.sizes   # EBML/WebM real, ~7 s a 32 kbps
print("E2E OK; audio recibido:", tr.sizes)
