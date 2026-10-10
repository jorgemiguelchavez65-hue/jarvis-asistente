"use strict";
// Jarvis PWA — sin dependencias ni paso de compilación.
const $ = id => document.getElementById(id);
const screens = ["login", "home", "visit", "report"];
let token = localStorage.getItem("jarvis_token") || "";
let cur = null;      // visita abierta: {id, ...}
let rec = null;      // estado de grabación
let pollTimer = null;

function show(name) { screens.forEach(s => $(s).hidden = s !== name); window.scrollTo(0, 0); }
function fmt(sec) { const m = Math.floor(sec / 60), s = Math.floor(sec % 60); return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0"); }

// ---------- API ----------
async function api(path, opts = {}) {
  const headers = Object.assign({ "X-Jarvis-Token": token }, opts.headers || {});
  if (opts.json) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
  const r = await fetch(path, Object.assign({}, opts, { headers }));
  if (r.status === 401) { logout(); throw new Error("Sesión no válida"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || "Error " + r.status);
  return data;
}

// ---------- IndexedDB: los trozos de audio se guardan según llegan ----------
function idb() {
  return new Promise((res, rej) => {
    const open = indexedDB.open("jarvis", 1);
    open.onupgradeneeded = () => open.result.createObjectStore("chunks", { autoIncrement: true }).createIndex("visit", "visit");
    open.onsuccess = () => res(open.result);
    open.onerror = () => rej(open.error);
  });
}
const tx = (db, mode) => db.transaction("chunks", mode).objectStore("chunks");
const done = r => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
async function putChunk(rec) { const db = await idb(); await done(tx(db, "readwrite").add(rec)); }
async function getChunks(visit) {          // [{key, visit, session, seq, mime, blob}] en orden de llegada
  const db = await idb(), s = tx(db, "readonly"), idx = s.index("visit");
  const keys = await done(idx.getAllKeys(visit)), out = [];
  for (const k of keys) out.push(Object.assign({ key: k }, await done(tx(db, "readonly").get(k))));
  return out;
}
async function delChunk(key) { const db = await idb(); await done(tx(db, "readwrite").delete(key)); }
async function clearChunks(visit) { for (const c of await getChunks(visit)) await delChunk(c.key); }
async function orphanIds() {
  const db = await idb(); const all = await done(tx(db, "readonly").getAll());
  return [...new Set(all.map(c => c.visit))];
}

// ---------- Sesión ----------
function logout() { localStorage.removeItem("jarvis_token"); token = ""; show("login"); }
$("login-form").onsubmit = async e => {
  e.preventDefault(); token = $("token").value.trim(); $("login-err").textContent = "Conectando… (si el servidor estaba dormido puede tardar hasta 1 minuto)";
  try { await api("/api/ping"); $("login-err").textContent = ""; localStorage.setItem("jarvis_token", token); await home(); }
  catch (x) { $("login-err").textContent = "Contraseña incorrecta o sin conexión."; token = ""; }
};
$("logout").onclick = logout;

// ---------- Inicio ----------
async function home() {
  show("home"); cur = null; clearInterval(pollTimer);
  const list = $("visit-list"); list.textContent = "";
  const wake = setTimeout(() => { list.innerHTML = '<p class="muted">Conectando… si el servidor estaba dormido (plan gratuito) puede tardar hasta 1 minuto.</p>'; }, 3000);
  try {
    const visits = await api("/api/visits");
    const labels = { open: "abierta", queued: "en cola", processing: "procesando", done: "informe listo", error: "con error" };
    visits.forEach(v => {
      const li = document.createElement("li");
      const t = document.createElement("div"); t.textContent = v.client;
      const sm = document.createElement("small"); sm.textContent = v.date + " · " + (labels[v.status] || v.status);
      t.appendChild(document.createElement("br")); t.appendChild(sm);
      li.appendChild(t); li.onclick = () => openVisit(v.id); list.appendChild(li);
    });
    if (!visits.length) list.innerHTML = '<p class="muted">Aún no hay visitas.</p>';
    const orphans = (await orphanIds()).filter(id => visits.some(v => v.id === id && v.status === "open"));
    $("orphans").textContent = "";
    if (orphans.length) {
      const d = document.createElement("div"); d.className = "warn";
      d.textContent = "Hay " + orphans.length + " grabación(es) guardada(s) en este teléfono sin enviar. Ábrela(s) desde la lista y pulsa «Terminar y generar informe».";
      $("orphans").appendChild(d);
    }
  } catch (x) { list.innerHTML = '<p class="muted">No se pudo cargar la lista (¿sin conexión?).</p>'; }
  finally { clearTimeout(wake); }
}
$("new-form").onsubmit = async e => {
  e.preventDefault(); $("new-err").textContent = "";
  try {
    const v = await api("/api/visits", { method: "POST", json: {
      client: $("n-client").value, contact: $("n-contact").value, consent: $("n-consent").checked } });
    $("new-form").reset(); openVisit(v.id);
  } catch (x) { $("new-err").textContent = x.message; }
};

// ---------- Visita ----------
async function openVisit(id) {
  try { cur = await api("/api/visits/" + id); } catch (x) { return alert(x.message); }
  if (cur.status !== "open") return showReport();
  show("visit"); $("v-err").textContent = "";
  $("v-title").textContent = cur.client + (cur.contact ? " · " + cur.contact : "");
  $("notes").value = cur.notes || ""; $("chat").textContent = "";
  cur.consulted.forEach(c => { addMsg("q", (c.photo ? "📷 " : "") + c.question); addMsg("a", c.answer); });
  setRecUi("idle");
  const left = (await getChunks(id)).length;
  setSync(left);
  if (left) { $("rec-msg").textContent = "Hay audio de esta visita guardado en el teléfono; se está enviando."; flush(id); }
}
function addMsg(cls, text) {
  const d = document.createElement("div"); d.className = "msg " + cls; d.textContent = text;
  $("chat").appendChild(d); d.scrollIntoView({ block: "nearest" }); return d;
}
$("back").onclick = async () => { if (rec && !confirm("La grabación sigue activa. ¿Salir? Se detendrá.")) return; await stopRec(); home(); };
$("back2").onclick = home;

// ---------- Envío de audio por trozos (mientras grabas) ----------
let flushing = null;
function setSync(n) { $("sync").textContent = n ? "☁ " + n + " trozo(s) de audio por enviar" : "☁ audio al día"; }
// Envía en orden los trozos guardados. Devuelve cuántos quedan sin enviar.
function flush(visitId) {
  const run = async () => {
    let left = (await getChunks(visitId)).length;
    for (const c of await getChunks(visitId)) {
      try {
        const r = await fetch("/api/visits/" + visitId + "/audio/" + c.session + "/" + c.seq,
          { method: "PUT", headers: { "X-Jarvis-Token": token, "Content-Type": c.mime.split(";")[0] }, body: c.blob });
        if (r.status === 401) { logout(); break; }
        if (r.ok || [400, 404, 409, 413, 415].includes(r.status)) { await delChunk(c.key); left--; if (!r.ok) $("v-err").textContent = "Un trozo de audio fue rechazado por el servidor (" + r.status + ")."; }
        else break;
      } catch (x) { break; }       // sin red: se reintenta luego, el trozo sigue guardado
    }
    return left;
  };
  flushing = (flushing || Promise.resolve()).then(run, run);
  return flushing.then(n => { if (cur && cur.id === visitId) setSync(n); return n; });
}
async function flushAll() { for (const id of await orphanIds()) await flush(id); }
addEventListener("online", () => { netUi(); flushAll(); });

// ---------- Grabación ----------
function setRecUi(state) {
  $("rec-start").hidden = state !== "idle"; $("rec-pause").hidden = state === "idle";
  $("rec-stop").hidden = state === "idle"; $("rec-box").classList.toggle("live", state === "rec");
  $("rec-pause").textContent = state === "paused" ? "▶ Reanudar" : "⏸ Pausa";
}
function tick() {
  if (!rec) return;
  const t = rec.acc + (rec.recorder.state === "recording" ? (Date.now() - rec.since) / 1000 : 0);
  $("timer").textContent = fmt(t);
}
async function startRec() {
  $("v-err").textContent = "";
  if (!navigator.mediaDevices || !window.MediaRecorder) return $("v-err").textContent = "Este navegador no puede grabar audio.";
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
  catch (x) { return $("v-err").textContent = "No hay permiso de micrófono. Actívalo en los ajustes del navegador."; }
  const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find(m => MediaRecorder.isTypeSupported(m)) || "";
  const recorder = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 32000 } : { audioBitsPerSecond: 32000 });
  const id = cur.id;
  // Cada pulsación de «Grabar» es una sesión (su propio archivo de audio); los trozos llevan un número de orden.
  rec = { recorder, stream, acc: 0, since: Date.now(), mime: recorder.mimeType || mime || "audio/webm", interrupted: false, wake: null,
          session: Date.now(), seq: 0, pending: Promise.resolve() };
  const me = rec;
  recorder.ondataavailable = e => {
    if (!e.data || !e.data.size) return;
    const item = { visit: id, session: me.session, seq: me.seq++, mime: me.mime, blob: e.data };
    me.pending = me.pending.then(() => putChunk(item)).then(() => flush(id))
      .catch(() => { $("v-err").textContent = "No se pudo guardar el audio en el teléfono (¿poco espacio?)."; });
  };
  stream.getAudioTracks()[0].onended = () => { if (rec) { rec.interrupted = true; $("rec-msg").textContent = "⚠ El micrófono se cortó. Detén y vuelve a grabar."; } };
  recorder.start(10000);   // un trozo cada 10 s, guardado al instante
  rec.timer = setInterval(tick, 500);
  try { rec.wake = await navigator.wakeLock.request("screen"); } catch (x) { /* no soportado */ }
  setRecUi("rec"); $("rec-msg").textContent = "Grabando. Mantén esta pantalla abierta y encendida.";
}
function pauseRec() {
  if (!rec) return;
  if (rec.recorder.state === "recording") { rec.acc += (Date.now() - rec.since) / 1000; rec.recorder.pause(); setRecUi("paused"); }
  else { rec.since = Date.now(); rec.recorder.resume(); setRecUi("rec"); }
}
function stopRec() {
  return new Promise(resolve => {
    if (!rec) return resolve();
    const r = rec; rec = null; clearInterval(r.timer);
    r.recorder.onstop = () => { r.stream.getTracks().forEach(t => t.stop()); if (r.wake) r.wake.release().catch(() => {}); r.pending.then(resolve); };
    if (r.recorder.state !== "inactive") r.recorder.stop(); else r.recorder.onstop();
    setRecUi("idle");
  });
}
document.addEventListener("visibilitychange", async () => {
  if (!rec) return;
  if (document.hidden) rec.interrupted = true;
  else {
    if (rec.wake === null || rec.wake.released) { try { rec.wake = await navigator.wakeLock.request("screen"); } catch (x) {} }
    if (rec.interrupted) $("rec-msg").textContent = "⚠ La app estuvo en segundo plano: ese tramo del audio puede faltar.";
  }
});
$("rec-start").onclick = startRec; $("rec-pause").onclick = pauseRec;
$("rec-stop").onclick = async () => { await stopRec(); $("rec-msg").textContent = "Grabación detenida. Se enviará al terminar la visita."; };

// ---------- Preguntas en vivo ----------
function shrink(file) {
  return new Promise((res, rej) => {
    const img = new Image(), url = URL.createObjectURL(file);
    img.onload = () => {
      const s = Math.min(1, 1280 / Math.max(img.width, img.height)), c = document.createElement("canvas");
      c.width = Math.round(img.width * s); c.height = Math.round(img.height * s);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url);
      res(c.toDataURL("image/jpeg", 0.8).split(",")[1]);
    };
    img.onerror = () => rej(new Error("No se pudo leer la foto")); img.src = url;
  });
}
$("ask-form").onsubmit = async e => {
  e.preventDefault();
  const q = $("q").value.trim(), file = $("photo").files[0];
  if (!q && !file) return;
  addMsg("q", (file ? "📷 " : "") + q); const wait = addMsg("a", "…");
  $("q").value = ""; const body = { question: q };
  try {
    if (file) body.image = await shrink(file);
    $("photo").value = "";
    const item = await api("/api/visits/" + cur.id + "/ask", { method: "POST", json: body });
    wait.textContent = item.answer;
  } catch (x) { wait.textContent = "No se pudo consultar: " + x.message; }
};

// ---------- Terminar ----------
$("finish").onclick = async () => {
  const btn = $("finish"); btn.disabled = true; $("v-err").textContent = "";
  try {
    await stopRec();
    btn.textContent = "Enviando audio…";
    const left = await flush(cur.id);
    if (left) throw new Error("Faltan " + left + " trozo(s) de audio por enviar. Revisa tu conexión y vuelve a pulsar; el audio sigue guardado en el teléfono.");
    const form = new FormData(); form.append("notes", $("notes").value);
    await api("/api/visits/" + cur.id + "/finish", { method: "POST", body: form });
    cur = await api("/api/visits/" + cur.id); showReport();
  } catch (x) { $("v-err").textContent = x.message; }
  finally { btn.disabled = false; btn.textContent = "Terminar y generar informe"; }
};

// ---------- Informe ----------
function showReport() {
  show("report"); clearInterval(pollTimer);
  const render = () => {
    const processing = cur.status === "processing" || cur.status === "queued", err = cur.status === "error", ok = cur.status === "done";
    $("r-status").textContent = processing ? "Procesando… esto puede tardar unos minutos según la duración. Puedes salir y volver." + (cur.error ? " (" + cur.error + ")" : "") : err ? "Algo falló: " + cur.error : "";
    $("r-md").textContent = ok ? cur.report_md : ""; $("r-md").hidden = !ok;
    $("r-actions").hidden = !ok; $("r-share").hidden = !navigator.share;
    $("r-retry").hidden = !err;
  };
  render();
  if (cur.status === "processing" || cur.status === "queued") pollTimer = setInterval(async () => {
    try { cur = await api("/api/visits/" + cur.id); render(); if (cur.status !== "processing" && cur.status !== "queued") clearInterval(pollTimer); } catch (x) { /* sigue intentando */ }
  }, 3000);
}
$("r-retry").onclick = async () => {
  try { await api("/api/visits/" + cur.id + "/finish", { method: "POST", body: new FormData() }); cur = await api("/api/visits/" + cur.id); showReport(); }
  catch (x) { $("r-status").textContent = x.message; }
};
$("r-copy").onclick = async () => { await navigator.clipboard.writeText(cur.report_md); $("r-copy").textContent = "Copiado ✓"; setTimeout(() => $("r-copy").textContent = "Copiar", 1500); };
$("r-share").onclick = () => navigator.share({ title: "Informe de visita — " + cur.client, text: cur.report_md }).catch(() => {});
$("r-dl").onclick = () => {
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([cur.report_md], { type: "text/markdown" }));
  a.download = "visita_" + cur.date + "_" + cur.client.replace(/[^\w-]+/g, "_") + ".md"; a.click();
};
$("r-del").onclick = async () => {
  if (!confirm("¿Borrar esta visita y su informe del servidor? No se puede deshacer.")) return;
  await api("/api/visits/" + cur.id, { method: "DELETE" }); await clearChunks(cur.id); home();
};

// ---------- Arranque ----------
function netUi() { $("net").hidden = navigator.onLine; }
addEventListener("offline", netUi); netUi();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
(async () => {
  if (!token) return show("login");
  try { await api("/api/ping"); await home(); } catch (x) { if (token) home(); }
  flushAll();
})();
