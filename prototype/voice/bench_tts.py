"""Kokoro (pf_dora) vs Piper (pt_BR-faber-medium): same sentences, timing and WAV files to listen to side by side.
Run in the Windows venv:  python bench_tts.py   (add --play to hear each one right away)."""
import sys
import wave

import numpy as np

from common import MODELS, OUT, SENTENCES, Timer

PLAY = "--play" in sys.argv


def save(path, samples: np.ndarray, rate: int) -> float:
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return len(samples) / rate


def play(samples: np.ndarray, rate: int) -> None:
    if PLAY:
        import sounddevice as sd
        sd.play(samples, rate)
        sd.wait()


def kokoro() -> None:
    from kokoro_onnx import Kokoro
    print("Kokoro pf_dora")
    with Timer("load"):
        engine = Kokoro(str(MODELS / "kokoro-v1.0.onnx"), str(MODELS / "voices-v1.0.bin"))
    for i, text in enumerate(SENTENCES, 1):
        with Timer(f"frase {i}") as t:
            samples, rate = engine.create(text, voice="pf_dora", speed=1.0, lang="pt-br")
        length = save(OUT / f"kokoro-{i}.wav", samples, rate)
        print(f"    áudio de {length:.1f} s, gerado em {t.seconds:.2f} s (fator {t.seconds / length:.2f})")
        play(samples, rate)


def piper() -> None:
    from piper import PiperVoice
    print("Piper pt_BR-faber-medium")
    with Timer("load"):
        voice = PiperVoice.load(str(MODELS / "pt_BR-faber-medium.onnx"))
    for i, text in enumerate(SENTENCES, 1):
        with Timer(f"frase {i}") as t:
            chunks = [c.audio_float_array for c in voice.synthesize(text)]
        samples = np.concatenate(chunks)
        rate = voice.config.sample_rate
        length = save(OUT / f"piper-{i}.wav", samples, rate)
        print(f"    áudio de {length:.1f} s, gerado em {t.seconds:.2f} s (fator {t.seconds / length:.2f})")
        play(samples, rate)


if __name__ == "__main__":
    for engine in (kokoro, piper):
        try:
            engine()
        except Exception as exc:  # one engine missing its model must not stop the other
            print(f"  falhou: {type(exc).__name__}: {exc}")
    print(f"WAVs em {OUT}")
