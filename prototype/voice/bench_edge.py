"""Edge-TTS (Microsoft's online neural voices, unofficial API, no key): the same sentences as bench_tts.py, to
listen to.  Run in the Windows venv:  python bench_edge.py   (WAV/MP3 files go to the output folder)."""
import asyncio
import time

import edge_tts

from common import OUT, SENTENCES

VOICES = ("pt-BR-AntonioNeural", "pt-PT-DuarteNeural")


async def main() -> None:
    for voice in VOICES:
        print(voice)
        for i, text in enumerate(SENTENCES, 1):
            path = OUT / f"edge-{voice.split('-')[1].lower()}-{i}.mp3"
            start = time.perf_counter()
            first = None
            with open(path, "wb") as out:
                async for chunk in edge_tts.Communicate(text, voice).stream():
                    if chunk["type"] == "audio":
                        if first is None:
                            first = time.perf_counter() - start
                        out.write(chunk["data"])
            print(f"  frase {i}: primeiro áudio em {first * 1000:.0f} ms, pronto em {(time.perf_counter() - start) * 1000:.0f} ms")
    print(f"arquivos em {OUT}")


asyncio.run(main())
