"""Punto de entrada de compatibilidad para hostings que arrancan con `python app.py`
(p. ej. un servicio de Render creado a mano) o con `uvicorn app:app`.

El arranque real vive en `jarvis.web.main`; el comando recomendado es `jarvis-server`.
"""
import sys
from pathlib import Path

# Permite arrancar desde una copia del repositorio aunque el paquete no esté instalado.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from jarvis.web.main import build_app, main  # noqa: E402


def __getattr__(name: str):
    """`uvicorn app:app` pide el atributo `app`; se construye solo en ese momento (necesita las variables de entorno)."""
    if name == "app":
        return build_app()
    raise AttributeError(name)


if __name__ == "__main__":
    main()
