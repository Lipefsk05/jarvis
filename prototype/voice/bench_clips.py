"""Compare Whisper models on YOUR recorded voice. Record with `python talk.py --save-audio` (clips go to
<output folder>\\clips, never leave the PC), then:

    python bench_clips.py                 local large-v3-turbo vs Groq whisper-large-v3 and whisper-large-v3-turbo
    python bench_clips.py --local-large   also the local large-v3 (downloads ~3 GB the first time)
    python bench_clips.py --only-phrases  skip the short name checks
    python bench_clips.py --no-groq       local models only: nothing leaves the PC
    python bench_clips.py --only-large --last 15 --no-groq   just the local large-v3 on the newest 15 clips (fast; the
                                          turbo's text is already in the "no momento" line)

Prints, per clip, what each model wrote and how long it took, then a summary. The Groq calls send the clips to Groq
(free tier, as the Telegram voice notes already do): run it only on clips you are fine sending."""
import argparse
import csv
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf

from common import OUT, add_cuda_dlls, read_env

PROMPT = "Jarvis, Dindin, Firebase, Mind, Groq, Telegram."


def groq(model: str, path: Path, key: str) -> tuple[str, float]:
    boundary = uuid.uuid4().hex
    fields = {"model": model, "language": "pt", "response_format": "json", "temperature": "0", "prompt": PROMPT}
    body = b""
    for name, value in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
             f"Content-Type: audio/wav\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request("https://api.groq.com/openai/v1/audio/transcriptions", body, {
        "Authorization": f"Bearer {key}", "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "jarvis-voice-prototype/0.1"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=60) as response:
        text = json.loads(response.read())["text"].strip()
    return text, time.perf_counter() - started


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)  # progress shows at once even when the output goes to a file or a pipe
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-large", action="store_true")
    parser.add_argument("--only-phrases", action="store_true")
    parser.add_argument("--no-groq", action="store_true")
    parser.add_argument("--only-large", action="store_true", help="load only the local large-v3 (the turbo text is already in the index)")
    parser.add_argument("--last", type=int, default=0, help="only the newest N clips")
    args = parser.parse_args()
    folder = OUT / "clips"
    index = folder / "clips.csv"
    if not index.exists():
        raise SystemExit(f"nenhum trecho em {folder}: rode `python talk.py --save-audio` e converse um pouco")
    rows = [r for r in csv.reader(index.open(encoding="utf-8")) if len(r) >= 4 and (r[1] == "frase" or not args.only_phrases)]
    if args.last:
        rows = rows[-args.last:]
    print(f"{len(rows)} trechos\n")

    add_cuda_dlls()
    from faster_whisper import WhisperModel
    local = {} if args.only_large else {"local turbo": WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")}
    if args.local_large or args.only_large:
        local["local large-v3"] = WhisperModel("large-v3", device="cuda", compute_type="float16")
    for model in local.values():
        list(model.transcribe(np.zeros(16000, dtype=np.float32), language="pt")[0])
    key = "" if args.no_groq else read_env("GROQ_API_KEY")
    times: dict[str, list[float]] = {}

    for name, kind, _, original in rows:
        path = folder / name
        if not path.exists():
            continue
        audio, _ = sf.read(path, dtype="float32")
        print(f"{name} ({kind}, {len(audio) / 16000:.1f} s)")
        print(f"   no momento (talk.py): {original}")
        results = {}
        for label, model in local.items():
            started = time.perf_counter()
            segments, _ = model.transcribe(audio, language="pt", beam_size=1, vad_filter=False,
                                           initial_prompt=None if kind == "checagem" else PROMPT,
                                           condition_on_previous_text=False)
            results[label] = (" ".join(s.text.strip() for s in segments), time.perf_counter() - started)
        for model in (() if args.no_groq else ("whisper-large-v3", "whisper-large-v3-turbo")):
            try:
                results[f"groq {model.removeprefix('whisper-')}"] = groq(model, path, key)
            except Exception as exc:  # a rate limit must not stop the comparison
                results[f"groq {model.removeprefix('whisper-')}"] = (f"(falhou: {type(exc).__name__})", 0.0)
        for label, (text, seconds) in results.items():
            times.setdefault(label, []).append(seconds)
            print(f"   {label:22s} {seconds:5.2f} s  {text}")
        print()
    print("tempo médio por trecho:")
    for label, values in times.items():
        print(f"   {label:22s} {sum(values) / len(values):.2f} s")


if __name__ == "__main__":
    main()
