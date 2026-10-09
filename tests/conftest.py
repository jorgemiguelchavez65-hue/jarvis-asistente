import dataclasses

import pytest

from jarvis.config import Config

from fakes import TOKEN, FakeClaude, FakeTranscriber


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(Config.load(), data_dir=tmp_path, anthropic_api_key="x", model="m",
                               access_token=TOKEN, keep_audio=False, max_audio_mb=1,
                               backend="local", stt="local")


@pytest.fixture
def fake_claude():
    return FakeClaude()


@pytest.fixture
def client(config, fake_claude):
    from fastapi.testclient import TestClient

    from jarvis.web.app import create_app

    app = create_app(config, claude=fake_claude, transcriber=FakeTranscriber(), background=False)
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {TOKEN}"
    return c
