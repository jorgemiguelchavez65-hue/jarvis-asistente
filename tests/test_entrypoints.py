"""El `app.py` de la raíz existe para hostings que arrancan con `python app.py` o `uvicorn app:app`."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_root_app():
    spec = importlib.util.spec_from_file_location("root_app", ROOT / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_root_app_py_exists_and_exposes_main():
    mod = load_root_app()
    assert callable(mod.main) and callable(mod.build_app)


def test_uvicorn_attribute_builds_the_real_app(monkeypatch, tmp_path):
    for k, v in {"JARVIS_BACKEND": "local", "JARVIS_STT": "api", "JARVIS_STT_BASE_URL": "http://x/v1",
                 "JARVIS_STT_API_KEY": "k", "JARVIS_STT_MODEL": "m", "ANTHROPIC_API_KEY": "x",
                 "JARVIS_ACCESS_TOKEN": "t" * 24, "JARVIS_DATA_DIR": str(tmp_path)}.items():
        monkeypatch.setenv(k, v)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = load_root_app().app
    assert isinstance(app, FastAPI)
    assert TestClient(app).get("/healthz").json() == {"ok": True}


def test_unknown_attribute_is_a_normal_attribute_error():
    with pytest.raises(AttributeError):
        load_root_app().nada


def test_requirements_txt_installs_the_render_extra():
    lines = [ln.strip() for ln in (ROOT / "requirements.txt").read_text().splitlines()
             if ln.strip() and not ln.startswith("#")]
    assert lines == [".[render]"]


def test_render_yaml_start_command_is_a_real_console_script():
    import tomllib

    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert "jarvis-server" in scripts and "startCommand: jarvis-server" in (ROOT / "render.yaml").read_text()
