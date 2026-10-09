"""Cómo se pone en marcha el procesamiento de una visita terminada."""
from __future__ import annotations

import threading
from typing import Callable


class InlineDispatcher:
    """Ejecuta en la misma petición (tests)."""

    def __init__(self, handle: Callable[[str], object]):
        self._handle = handle

    def enqueue(self, visit_id: str) -> None:
        self._handle(visit_id)


class ThreadDispatcher:
    """Hilo en segundo plano. El estado vive en la base de datos, así que si la instancia se
    reinicia o se duerme a mitad del trabajo, `recover_pending` lo retoma al volver a arrancar."""

    def __init__(self, handle: Callable[[str], object]):
        self._handle = handle

    def enqueue(self, visit_id: str) -> None:
        threading.Thread(target=self._handle, args=(visit_id,), daemon=True).start()
