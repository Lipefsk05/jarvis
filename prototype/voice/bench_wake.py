"""Test an openWakeWord model on YOUR recorded clips (`python talk.py --save-audio` keeps them in <output>\\clips).

    python bench_wake.py                     pretrained "hey_jarvis" on every clip
    python bench_wake.py --model caminho.onnx   a model you trained
    python bench_wake.py --last 20           only the newest 20 clips

Prints, per clip, the highest score (0-1) the model gave and what talk.py's Whisper had written, so you can see which
clips with the name fire and which without it stay quiet. Nothing leaves the PC."""
import argparse
import csv
import sys

import numpy as np
import soundfile as sf

from common import OUT

FRAME = 1280  # 80 ms at 16 kHz, the size openWakeWord wants
THRESHOLD = 0.5


def best_score(model, audio: np.ndarray) -> float:
    model.reset()
    pcm = np.concatenate([np.zeros(16000, dtype=np.float32), audio, np.zeros(16000, dtype=np.float32)])
    pcm = (np.clip(pcm, -1.0, 1.0) * 32767).astype(np.int16)
    best = 0.0
    for start in range(0, len(pcm) - FRAME + 1, FRAME):
        scores = model.predict(pcm[start:start + FRAME])
        best = max(best, max(scores.values()))
    return best


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="hey_jarvis")
    parser.add_argument("--last", type=int, default=0)
    args = parser.parse_args()
    from openwakeword.model import Model
    model = Model(wakeword_models=[args.model], inference_framework="onnx")

    folder = OUT / "clips"
    rows = [r for r in csv.reader((folder / "clips.csv").open(encoding="utf-8")) if len(r) >= 4]
    if args.last:
        rows = rows[-args.last:]
    print(f"{len(rows)} trechos, limiar {THRESHOLD}\n")
    for name, kind, _, original in rows:
        path = folder / name
        if not path.exists():
            continue
        audio, _ = sf.read(path, dtype="float32")
        score = best_score(model, audio)
        mark = "DISPAROU" if score >= THRESHOLD else "        "
        print(f"{score:.2f} {mark} {kind:9s} {name}  «{original}»")


if __name__ == "__main__":
    main()
