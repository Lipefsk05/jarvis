"""faster-whisper on the GPU: load time, transcription time and VRAM, over the WAVs bench_tts.py wrote
(or any WAV given as argument).  Run in the Windows venv:  python bench_stt.py [arquivo.wav ...]"""
import subprocess
import sys

import numpy as np
import soundfile as sf

from common import OUT, Timer, add_cuda_dlls

add_cuda_dlls()
from faster_whisper import WhisperModel  # noqa: E402  (needs the DLL path first)


def load_16k(path: str) -> np.ndarray:
    """The WAV as mono float32 at 16 kHz (what the microphone will deliver). Read here instead of by the
    decoder built into faster-whisper, which needs a compatible PyAV."""
    audio, rate = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != 16000:
        audio = np.interp(np.linspace(0, len(audio), int(len(audio) * 16000 / rate), endpoint=False),
                          np.arange(len(audio)), audio).astype(np.float32)
    return audio


def vram_mb() -> int:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout
    return int(out.split()[0])


files = sys.argv[1:] or sorted(str(p) for p in OUT.glob("*.wav"))
print(f"VRAM antes: {vram_mb()} MiB")
with Timer("carregar large-v3-turbo (float16)"):
    model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")
print(f"VRAM depois: {vram_mb()} MiB")
for path in files:
    audio = load_16k(path)
    with Timer(path.rsplit("\\", 1)[-1]):
        segments, info = model.transcribe(audio, language="pt", beam_size=1, vad_filter=False)
        text = " ".join(s.text.strip() for s in segments)
    print(f"    “{text}”")
