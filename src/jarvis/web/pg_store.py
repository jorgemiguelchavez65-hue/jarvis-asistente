"""Almacén en Postgres (Neon, Supabase, Render…): visitas y audio temporal.

Sirve para hosting sin disco permanente. Las operaciones que no deben pisarse entre sí
(tomar un trabajo, añadir una consulta) son una sola sentencia SQL atómica.
"""
from __future__ import annotations

import time
from pathlib import Path

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from jarvis.web.store import LIST_FIELDS, check_id, group_sessions, new_visit_record, part_name

SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    id text PRIMARY KEY,
    created text NOT NULL,
    data jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS visits_created ON visits (created DESC);
CREATE TABLE IF NOT EXISTS audio_parts (
    visit_id text NOT NULL,
    session bigint NOT NULL,
    seq integer NOT NULL,
    ext text NOT NULL,
    data bytea NOT NULL,
    PRIMARY KEY (visit_id, session, seq)
);
"""


class PostgresStore:
    def __init__(self, url: str, max_size: int = 5):
        # check_connection: Neon y otros suspenden conexiones inactivas; así se detecta y se reabre.
        self._pool = ConnectionPool(url, min_size=1, max_size=max_size, open=True,
                                    kwargs={"autocommit": True}, check=ConnectionPool.check_connection)
        with self._pool.connection() as c:
            c.execute(SCHEMA)

    # --- visitas ---
    def create(self, client: str, contact: str, day: str | None) -> dict:
        visit = new_visit_record(client, contact, day)
        with self._pool.connection() as c:
            c.execute("INSERT INTO visits (id, created, data) VALUES (%s, %s, %s)",
                      (visit["id"], visit["created"], Jsonb(visit)))
        return visit

    def get(self, visit_id: str) -> dict:
        with self._pool.connection() as c:
            row = c.execute("SELECT data FROM visits WHERE id = %s", (check_id(visit_id),)).fetchone()
        if row is None:
            raise KeyError(visit_id)
        return row[0]

    def update(self, visit_id: str, **changes) -> dict:
        patch = {**changes, "updated_at": time.time()}
        with self._pool.connection() as c:
            row = c.execute("UPDATE visits SET data = data || %s WHERE id = %s RETURNING data",
                            (Jsonb(patch), check_id(visit_id))).fetchone()
        if row is None:
            raise KeyError(visit_id)
        return row[0]

    def append_consulted(self, visit_id: str, item: dict) -> None:
        with self._pool.connection() as c:  # una sola sentencia: dos preguntas a la vez no se pisan
            c.execute("UPDATE visits SET data = jsonb_set(data, '{consulted}', "
                      "COALESCE(data->'consulted', '[]'::jsonb) || %s) WHERE id = %s",
                      (Jsonb([item]), check_id(visit_id)))

    def list(self) -> list[dict]:
        fields = ", ".join(f"data->>'{f}'" for f in LIST_FIELDS if f not in ("id", "created"))
        with self._pool.connection() as c:
            rows = c.execute(f"SELECT id, created, {fields} FROM visits ORDER BY created DESC").fetchall()
        keys = [f for f in LIST_FIELDS if f not in ("id", "created")]
        return [{"id": r[0], "created": r[1], **dict(zip(keys, r[2:]))} for r in rows]

    def delete(self, visit_id: str) -> None:
        with self._pool.connection() as c:
            c.execute("DELETE FROM visits WHERE id = %s", (check_id(visit_id),))
        self.discard_audio(visit_id)

    def claim(self, visit_id: str, stale_after: float) -> bool:
        """Toma la visita para procesarla. Atómico: con varios intentos a la vez, solo uno gana."""
        now = time.time()
        with self._pool.connection() as c:
            cur = c.execute(
                "UPDATE visits SET data = data || %s WHERE id = %s AND ("
                " data->>'status' = 'queued' OR"
                " (data->>'status' = 'processing' AND COALESCE((data->>'claimed_at')::float, 0) < %s))",
                (Jsonb({"status": "processing", "claimed_at": now, "updated_at": now}),
                 check_id(visit_id), now - stale_after))
            return cur.rowcount == 1

    # --- audio por trozos ---
    def save_part(self, visit_id: str, session: int, seq: int, ext: str, data: bytes,
                  max_total: int) -> None:
        visit_id = check_id(visit_id)
        with self._pool.connection() as c:
            # La comprobación del tope y la inserción van en una transacción por visita.
            with c.transaction():
                c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (visit_id,))
                used = c.execute(
                    "SELECT COALESCE(SUM(length(data)), 0) FROM audio_parts "
                    "WHERE visit_id = %s AND NOT (session = %s AND seq = %s)",
                    (visit_id, session, seq)).fetchone()[0]
                if used + len(data) > max_total:
                    raise ValueError("limit")
                c.execute(
                    "INSERT INTO audio_parts (visit_id, session, seq, ext, data) VALUES (%s,%s,%s,%s,%s) "
                    "ON CONFLICT (visit_id, session, seq) DO UPDATE SET ext = EXCLUDED.ext, data = EXCLUDED.data",
                    (visit_id, session, seq, ext, data))

    def materialize_audio(self, visit_id: str, workdir: Path) -> list[Path]:
        with self._pool.connection() as c:
            rows = c.execute("SELECT session, seq, ext, data FROM audio_parts WHERE visit_id = %s "
                             "ORDER BY session, seq", (check_id(visit_id),)).fetchall()
        by_name = {part_name(s, q, e): bytes(d) for s, q, e, d in rows}
        out = []
        for i, group in enumerate(group_sessions(list(by_name))):
            dest = workdir / f"{i:03d}.{group[0].rsplit('.', 1)[1]}"
            with dest.open("wb") as fh:
                for n in group:
                    fh.write(by_name[n])
            out.append(dest)
        return out

    def discard_audio(self, visit_id: str) -> None:
        with self._pool.connection() as c:
            c.execute("DELETE FROM audio_parts WHERE visit_id = %s", (check_id(visit_id),))
