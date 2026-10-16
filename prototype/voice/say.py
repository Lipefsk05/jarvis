"""Speak the given sentences with an Edge-TTS voice and play them.  python say.py [--voice pt-BR-AntonioNeural] "frase 1" "frase 2" ..."""
import asyncio
import sys

import edge_tts
import sounddevice as sd
import soundfile as sf

from pathlib import Path

from common import OUT

SRC = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC / "src"))
from jarvis.pronunciation import for_speech, load  # noqa: E402  (stdlib-only module, imported without installing jarvis)

TABLE = load(SRC / "persona" / "pronuncias.json")

from effect import LEVELS, robotize

args = sys.argv[1:]
voice = "pt-BR-AntonioNeural"
fx = 0.0
while args[:1] in (["--voice"], ["--fx"]):
    if args[0] == "--voice":
        voice = args[1]
    else:
        fx = LEVELS.get(args[1], 0.0)
    args = args[2:]


async def speak(i: int, text: str) -> None:
    path = OUT / f"say-{i}.mp3"
    await edge_tts.Communicate(for_speech(text, TABLE), voice).save(str(path))
    audio, rate = sf.read(str(path), dtype="float32")
    print(f"{i}: {text}")
    sd.play(robotize(audio, rate, fx), rate)
    sd.wait()


for n, sentence in enumerate(args, 1):
    asyncio.run(speak(n, sentence))
