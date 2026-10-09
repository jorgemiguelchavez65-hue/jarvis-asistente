"""Almacén de visitas. `LocalStore` (archivos) para desarrollo y tests; ver firestore_store.py para la nube.

Interfaz común (la usan app.py y pipeline.py):
  create, get, update, append_consulted, list, delete,
  save_part, materialize_audio, discard_audio, claim
"""
from __future__ import annotations

import re
import secrets
import shutil
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

from jarvis.storage import JsonStore

_ID = re.compile(r"^[A-Za-z0-9_-]{8,40}$")
LIST_FIELDS = ("id", "created", "date", "client", "status")


def check_id(visit_id: str) -> str:
    if not _ID.match(visit_id):  # evita rutas tipo ../../
        raise KeyError(visit_id)
    return visit_id


def new_visit_record(client: str, contact: str, day: str | None) -> dict:
    return {
        "id": secrets.token_urlsafe(9),
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "date": day or date.today().isoformat(),
        "client": client, "contact": contact,
        "consent": True,  # la app no deja crear la visita sin confirmarlo
        "status": "open",  # open -> queued -> processing -> done | error
        "error": "", "notes": "", "consulted": [], "transcript": "",
        "report": None, "report_md": "",
        "updated_at": time.time(), "claimed_at": 0.0,
    }


def group_sessions(names: list[str]) -> list[list[str]]:
    """Agrupa nombres '<sesion>_<seq>.<ext>' por sesión, cada grupo en orden de secuencia."""
    groups: dict[str, list[str]] = {}
    for n in sorted(names):  # sesión y seq van con ceros a la izquierda: orden lexicográfico = numérico
        groups.setdefault(n.split("_")[0], []).append(n)
    return [groups[k] for k in sorted(groups)]


def part_name(session: int, seq: int, ext: str) -> str:
    return f"{session:013d}_{seq:06d}.{ext}"


class LocalStore:
    def __init__(self, data_dir: Path):
        self.dir = data_dir / "visits"
        self.audio_dir = data_dir / "audio"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, visit_id: str) -> Path:
        return self.dir / f"{check_id(visit_id)}.json"

    # --- visitas ---
    def create(self, client: str, contact: str, day: str | None) -> dict:
        visit = new_visit_record(client, contact, day)
        self._save(visit)
        return visit

    def get(self, visit_id: str) -> dict:
        path = self._path(visit_id)
        if not path.exists():
            raise KeyError(visit_id)
        return JsonStore(path).load({})

    def _save(self, visit: dict) -> None:
        with self._lock:
            JsonStore(self._path(visit["id"])).save(visit)

    def update(self, visit_id: str, **changes) -> dict:
        with self._lock:  # lectura-modificación-escritura atómica entre hilos
            visit = self.get(visit_id)
            visit.update(changes, updated_at=time.time())
            self._save(visit)
            return visit

    def append_consulted(self, visit_id: str, item: dict) -> None:
        with self._lock:
            visit = self.get(visit_id)
            visit["consulted"].append(item)
            self._save(visit)

    def list(self) -> list[dict]:
        out = []
        for p in self.dir.glob("*.json"):
            v = JsonStore(p).load({})
            if v:
                out.append({k: v[k] for k in LIST_FIELDS})
        return sorted(out, key=lambda v: v["created"], reverse=True)

    def delete(self, visit_id: str) -> None:
        self._path(visit_id).unlink(missing_ok=True)
        self.discard_audio(visit_id)

    def claim(self, visit_id: str, stale_after: float) -> bool:
        """Toma la visita para procesarla. False si ya está hecha o la procesa otro."""
        with self._lock:
            v = self.get(visit_id)
            now = time.time()
            if v["status"] == "processing" and now - v.get("claimed_at", 0) < stale_after:
                return False
            if v["status"] not in ("queued", "processing"):
                return False
            self.update(visit_id, status="processing", claimed_at=now)
            return True

    # --- audio por trozos ---
    def _parts_dir(self, visit_id: str) -> Path:
        return self.audio_dir / check_id(visit_id)

    def save_part(self, visit_id: str, session: int, seq: int, ext: str, data: bytes,
                  max_total: int) -> None:
        d = self._parts_dir(visit_id)
        d.mkdir(parents=True, exist_ok=True)
        target = d / part_name(session, seq, ext)
        with self._lock:
            used = sum(f.stat().st_size for f in d.iterdir() if f != target and f.suffix != ".tmp")
            if used + len(data) > max_total:
                raise ValueError("limit")
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)  # reenviar el mismo trozo lo sobrescribe: es idempotente

    def materialize_audio(self, visit_id: str, workdir: Path) -> list[Path]:
        """Une los trozos de cada sesión de grabación en un archivo local por sesión."""
        d = self._parts_dir(visit_id)
        if not d.exists():
            return []
        names = [f.name for f in d.iterdir() if f.suffix != ".tmp"]
        out = []
        for i, group in enumerate(group_sessions(names)):
            dest = workdir / f"{i:03d}.{group[0].rsplit('.', 1)[1]}"
            with dest.open("wb") as fh:
                for n in group:
                    fh.write((d / n).read_bytes())
            out.append(dest)
        return out

    def discard_audio(self, visit_id: str) -> None:
        shutil.rmtree(self._parts_dir(visit_id), ignore_errors=True)

    def mark_interrupted(self) -> None:
        """Solo para un servidor único (local): lo que quedó procesándose por un reinicio se reintenta."""
        for item in self.list():
            if item["status"] == "processing":
                self.update(item["id"], status="error",
                            error="El servidor se reinició durante el proceso. Reintenta.")
