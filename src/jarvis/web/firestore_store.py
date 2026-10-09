"""Almacén en la nube: visitas en Firestore, trozos de audio en Cloud Storage.

Pensado para Cloud Run escalado a cero: no guarda nada en el disco de la instancia.
"""
from __future__ import annotations

import time
from pathlib import Path

from jarvis.web.store import LIST_FIELDS, check_id, group_sessions, new_visit_record, part_name


class FirestoreStore:
    def __init__(self, db, bucket, collection: str = "visits"):
        """`db` es un google.cloud.firestore.Client y `bucket` un google.cloud.storage.Bucket."""
        from google.cloud import firestore

        self._fs = firestore
        self._db = db
        self._col = db.collection(collection)
        self._bucket = bucket

    def _doc(self, visit_id: str):
        return self._col.document(check_id(visit_id))

    # --- visitas ---
    def create(self, client: str, contact: str, day: str | None) -> dict:
        visit = new_visit_record(client, contact, day)
        self._doc(visit["id"]).set(visit)
        return visit

    def get(self, visit_id: str) -> dict:
        snap = self._doc(visit_id).get()
        if not snap.exists:
            raise KeyError(visit_id)
        return snap.to_dict()

    def update(self, visit_id: str, **changes) -> dict:
        ref = self._doc(visit_id)
        try:
            ref.update({**changes, "updated_at": time.time()})
        except Exception as exc:  # google.api_core.exceptions.NotFound
            if type(exc).__name__ == "NotFound":
                raise KeyError(visit_id) from None
            raise
        return ref.get().to_dict()

    def append_consulted(self, visit_id: str, item: dict) -> None:
        # ArrayUnion es atómico: dos preguntas casi simultáneas no se pisan.
        self._doc(visit_id).update({"consulted": self._fs.ArrayUnion([item])})

    def list(self) -> list[dict]:
        q = self._col.order_by("created", direction=self._fs.Query.DESCENDING).select(list(LIST_FIELDS))
        return [d.to_dict() for d in q.stream()]

    def delete(self, visit_id: str) -> None:
        self._doc(visit_id).delete()
        self.discard_audio(visit_id)

    def claim(self, visit_id: str, stale_after: float) -> bool:
        ref = self._doc(visit_id)

        @self._fs.transactional
        def txn(transaction) -> bool:
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                return False
            v = snap.to_dict()
            now = time.time()
            if v["status"] == "processing" and now - v.get("claimed_at", 0) < stale_after:
                return False
            if v["status"] not in ("queued", "processing"):
                return False
            transaction.update(ref, {"status": "processing", "claimed_at": now, "updated_at": now})
            return True

        return txn(self._db.transaction())

    # --- audio por trozos (objetos audio/<visita>/<sesion>_<seq>.<ext>) ---
    def _prefix(self, visit_id: str) -> str:
        return f"audio/{check_id(visit_id)}/"

    def save_part(self, visit_id: str, session: int, seq: int, ext: str, data: bytes,
                  max_total: int) -> None:
        prefix = self._prefix(visit_id)
        target = prefix + part_name(session, seq, ext)
        used = sum(b.size for b in self._bucket.list_blobs(prefix=prefix) if b.name != target)
        if used + len(data) > max_total:
            raise ValueError("limit")
        self._bucket.blob(target).upload_from_string(data, content_type=f"audio/{ext}")

    def materialize_audio(self, visit_id: str, workdir: Path) -> list[Path]:
        prefix = self._prefix(visit_id)
        names = [b.name[len(prefix):] for b in self._bucket.list_blobs(prefix=prefix)]
        out = []
        for i, group in enumerate(group_sessions(names)):
            dest = workdir / f"{i:03d}.{group[0].rsplit('.', 1)[1]}"
            with dest.open("wb") as fh:
                for n in group:
                    fh.write(self._bucket.blob(prefix + n).download_as_bytes())
            out.append(dest)
        return out

    def discard_audio(self, visit_id: str) -> None:
        for b in list(self._bucket.list_blobs(prefix=self._prefix(visit_id))):
            b.delete()

    def mark_interrupted(self) -> None:
        """No hace nada en la nube: las instancias arrancan y se apagan todo el tiempo, y otra
        puede estar procesando. Los trabajos colgados los resuelven `claim` y el vencimiento."""
