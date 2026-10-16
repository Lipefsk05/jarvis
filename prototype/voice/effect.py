"""A light robotic colour for the voice, in numpy: a little ring modulation (the 'robot' tremble) plus a very short
echo (a metallic edge). `amount` goes 0 (clean) to 1 (very robotic); the first levels are meant to be subtle."""
import numpy as np

LEVELS = {"off": 0.0, "leve": 0.25, "medio": 0.5, "forte": 0.8}


def robotize(audio: np.ndarray, rate: int, amount: float) -> np.ndarray:
    if amount <= 0:
        return audio
    t = np.arange(len(audio)) / rate
    ring = audio * np.sin(2 * np.pi * 60 * t)                    # 60 Hz carrier
    mixed = (1 - 0.5 * amount) * audio + 0.5 * amount * ring
    delay = int(rate * 0.006)                                    # 6 ms
    echo = np.zeros_like(mixed)
    echo[delay:] = mixed[:-delay]
    out = mixed + 0.35 * amount * echo
    peak = float(np.max(np.abs(out))) or 1.0
    return (out * min(1.0, 0.95 / peak) * (float(np.max(np.abs(audio))) / peak if peak > 1 else 1.0)).astype(np.float32)
