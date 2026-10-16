"""Google Cloud Text-to-Speech, Chirp 3 HD voices in pt-BR: list them and speak the sample sentences.
Needs GOOGLE_TTS_API_KEY in the repo's .env (an API key restricted to the Text-to-Speech API).

    python bench_google.py                  list the pt-BR Chirp 3 HD voices and play 2 sentences with 3 male ones
    python bench_google.py Charon Fenrir    play with the named voices (the part after "Chirp3-HD-")
    python bench_google.py --list           only list the voices
"""
import base64
import io
import json
import sys
import time
import urllib.request

import sounddevice as sd
import soundfile as sf

from common import OUT, SENTENCES, read_env

KEY = read_env("GOOGLE_TTS_API_KEY")
BASE = "https://texttospeech.googleapis.com/v1"


def call(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{BASE}/{path}{'&' if '?' in path else '?'}key={KEY}", data,
                                     {"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def voices() -> list[dict]:
    found = call("voices?languageCode=pt-BR").get("voices", [])
    return sorted((v for v in found if "Chirp3-HD" in v["name"]), key=lambda v: (v["ssmlGender"], v["name"]))


def speak(name: str, text: str) -> None:
    start = time.perf_counter()
    reply = call("text:synthesize", {"input": {"text": text},
                                     "voice": {"languageCode": "pt-BR", "name": name},
                                     "audioConfig": {"audioEncoding": "MP3"}})
    took = time.perf_counter() - start
    audio, rate = sf.read(io.BytesIO(base64.b64decode(reply["audioContent"])), dtype="float32")
    print(f"  {name}: {took * 1000:.0f} ms para {len(audio) / rate:.1f} s de áudio, {len(text)} caracteres")
    sd.play(audio, rate)
    sd.wait()


if __name__ == "__main__":
    available = voices()
    print(f"{len(available)} vozes Chirp 3 HD em pt-BR:")
    for v in available:
        print(f"  {v['name'].split('Chirp3-HD-')[1]:12} {v['ssmlGender']}")
    if "--list" in sys.argv:
        sys.exit()
    wanted = [a for a in sys.argv[1:] if not a.startswith("--")]
    names = [f"pt-BR-Chirp3-HD-{w}" for w in wanted] or [v["name"] for v in available if v["ssmlGender"] == "MALE"][:3]
    for name in names:
        print(name)
        for text in SENTENCES[:2] + ["O backend do Dindin usa Firebase."]:
            speak(name, text)
