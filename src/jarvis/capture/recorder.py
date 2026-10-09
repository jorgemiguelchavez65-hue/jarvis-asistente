"""Grabación del micrófono hasta Ctrl+C. Escribe un WAV mono 16 kHz."""
from __future__ import annotations

import wave
from pathlib import Path

SAMPLE_RATE = 16_000


def record_until_interrupt(out_path: Path) -> Path:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("Instala el extra de audio: pip install -e '.[audio]'") from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    print("Grabando… pulsa Ctrl+C para terminar.")
    with wave.open(str(out_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        # Se escribe a disco por bloques: si algo falla no se pierde la visita entera.
        try:
            with sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
                while True:
                    data, _ = stream.read(SAMPLE_RATE)
                    wav.writeframes(bytes(data))
        except KeyboardInterrupt:
            pass
    return out_path
