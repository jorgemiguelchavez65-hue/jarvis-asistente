"""Configuración central: rutas y variables de entorno."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data_dir: Path
    reports_dir: Path
    anthropic_api_key: str | None
    model: str

    @classmethod
    def load(cls) -> "Config":
        data_dir = Path(os.environ.get("JARVIS_DATA_DIR", "data")).resolve()
        reports_dir = Path(os.environ.get("JARVIS_REPORTS_DIR", "informes")).resolve()
        return cls(
            data_dir=data_dir,
            reports_dir=reports_dir,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            model=os.environ.get("JARVIS_MODEL", "claude-sonnet-5-5"),
        )
