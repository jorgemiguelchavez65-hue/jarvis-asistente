"""Visitas en disco: un JSON por visita en <data>/visits/ (en la nube, un volumen persistente)."""
from __future__ import annotations

import re
import secrets
import threading
from datetime import date, datetime, timezone
from pathlib import Path

from jarvis.storage import JsonStore

_ID = re.compile(r"^[A-Za-z0-9_-]{8,40}$")


class VisitStore:
    def __init__(self, data_dir: Path):
        self.dir = data_dir / "visits"
        self.audio_dir = data_dir / "audio"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, visit_id: str) -> Path:
        if not _ID.match(visit_id):  # evita rutas tipo ../../
            raise KeyError(visit_id)
        return self.dir / f"{visit_id}.json"

    def create(self, client: str, contact: str, day: str | None) -> dict:
        visit = {
            "id": secrets.token_urlsafe(9),
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "date": day or date.today().isoformat(),
            "client": client, "contact": contact,
            "consent": True,  # la app no deja crear la visita sin confirmarlo
            "status": "open", "error": "",
            "notes": "", "consulted": [], "transcript": "",
            "report": None, "report_md": "",
        }
        self.save(visit)
        return visit

    def get(self, visit_id: str) -> dict:
        path = self._path(visit_id)
        if not path.exists():
            raise KeyError(visit_id)
        return JsonStore(path).load({})

    def save(self, visit: dict) -> None:
        with self._lock:
            JsonStore(self._path(visit["id"])).save(visit)

    def update(self, visit_id: str, **changes) -> dict:
        with self._lock:  # lectura-modificación-escritura atómica entre hilos
            visit = self.get(visit_id)
            visit.update(changes)
            self.save(visit)
            return visit

    def append_consulted(self, visit_id: str, item: dict) -> None:
        with self._lock:
            visit = self.get(visit_id)
            visit["consulted"].append(item)
            self.save(visit)

    def list(self) -> list[dict]:
        out = []
        for p in self.dir.glob("*.json"):
            v = JsonStore(p).load({})
            if v:
                out.append({k: v[k] for k in ("id", "created", "date", "client", "status")})
        return sorted(out, key=lambda v: v["created"], reverse=True)

    def delete(self, visit_id: str) -> None:
        self._path(visit_id).unlink(missing_ok=True)
        for f in self.audio_dir.glob(f"{visit_id}.*"):
            f.unlink(missing_ok=True)

    def audio_files(self, visit_id: str) -> list[Path]:
        return sorted(self.audio_dir.glob(f"{visit_id}.*"))

    def mark_interrupted(self) -> None:
        """Al arrancar: lo que quedó 'processing' por un reinicio se marca para reintentar."""
        for item in self.list():
            if item["status"] == "processing":
                self.update(item["id"], status="error",
                            error="El servidor se reinició durante el proceso. Reintenta.")
