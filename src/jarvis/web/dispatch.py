"""Cómo se pone en marcha el procesamiento de una visita terminada."""
from __future__ import annotations

import datetime
import threading
from typing import Callable


class InlineDispatcher:
    """Ejecuta en la misma petición (tests)."""

    def __init__(self, handle: Callable[[str], object]):
        self._handle = handle

    def enqueue(self, visit_id: str) -> None:
        self._handle(visit_id)


class ThreadDispatcher:
    """Hilo en segundo plano (servidor local de una sola instancia)."""

    def __init__(self, handle: Callable[[str], object]):
        self._handle = handle

    def enqueue(self, visit_id: str) -> None:
        threading.Thread(target=self._handle, args=(visit_id,), daemon=True).start()


class CloudTasksDispatcher:
    """Encola una tarea que Cloud Tasks entregará a /internal/process/<id> con un token OIDC."""

    DEADLINE = datetime.timedelta(minutes=30)  # máximo que admite Cloud Tasks para destinos HTTP

    def __init__(self, client, *, project: str, location: str, queue: str, service_url: str,
                 service_account: str):
        self._client = client
        self._parent = client.queue_path(project, location, queue)
        self._url = service_url.rstrip("/")
        self._sa = service_account

    def enqueue(self, visit_id: str) -> None:
        self._client.create_task(request={
            "parent": self._parent,
            "task": {
                "http_request": {
                    "http_method": "POST",
                    "url": f"{self._url}/internal/process/{visit_id}",
                    "oidc_token": {"service_account_email": self._sa, "audience": self._url},
                },
                "dispatch_deadline": self.DEADLINE,
            },
        })


def make_task_verifier(service_url: str, service_account: str):
    """Comprueba que la llamada a /internal/* viene de Cloud Tasks (token OIDC de nuestra cuenta)."""
    from fastapi import HTTPException
    from google.auth.transport import requests as greq
    from google.oauth2 import id_token

    audience = service_url.rstrip("/")

    def verify(request) -> None:
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            raise HTTPException(401, "No autorizado")
        try:
            claims = id_token.verify_oauth2_token(header[7:], greq.Request(), audience=audience)
        except ValueError:
            raise HTTPException(401, "Token no válido") from None
        if claims.get("email") != service_account or not claims.get("email_verified"):
            raise HTTPException(403, "Cuenta no permitida")

    return verify
