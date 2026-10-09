import httpx
import pytest

from jarvis.capture.api_transcriber import ApiTranscriber, TranscriptionError


def audio(tmp_path, size=100, name="000.webm"):
    f = tmp_path / name
    f.write_bytes(b"\x1a\x45\xdf\xa3" + b"0" * size)
    return f


def make(handler, **kw):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ApiTranscriber("https://stt.example/openai/v1/", "clave", "modelo-x", client=client,
                          backoff=0, **kw)


def test_sends_authenticated_multipart_and_returns_text(tmp_path):
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.read()
        return httpx.Response(200, text="  hola, esto es una prueba \n")

    assert make(handler).transcribe(audio(tmp_path)) == "hola, esto es una prueba"
    assert seen["url"] == "https://stt.example/openai/v1/audio/transcriptions"
    assert seen["auth"] == "Bearer clave"
    for needle in (b'name="model"', b"modelo-x", b'name="language"', b"es", b'filename="000.webm"',
                   b"audio/webm"):
        assert needle in seen["body"], needle


def test_retries_transient_errors_then_succeeds(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, text="limite") if len(calls) < 3 else httpx.Response(200, text="ok")

    assert make(handler).transcribe(audio(tmp_path)) == "ok" and len(calls) == 3


def test_does_not_retry_permanent_errors(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, text="clave inválida")

    with pytest.raises(TranscriptionError, match="401"):
        make(handler).transcribe(audio(tmp_path))
    assert len(calls) == 1


def test_gives_up_after_retries_with_reason(tmp_path):
    with pytest.raises(TranscriptionError, match="503"):
        make(lambda r: httpx.Response(503, text="caído")).transcribe(audio(tmp_path))


def test_network_errors_are_retried(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("sin red")
        return httpx.Response(200, text="ok")

    assert make(handler).transcribe(audio(tmp_path)) == "ok"


def test_oversize_file_fails_with_actionable_message(tmp_path):
    big = tmp_path / "000.webm"
    with big.open("wb") as fh:
        fh.truncate(26 * 1024 * 1024)
    with pytest.raises(TranscriptionError, match="Detén la grabación"):
        make(lambda r: httpx.Response(200, text="x")).transcribe(big)
