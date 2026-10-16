"""Shared bits of the voice prototype (Windows Python): CUDA DLL path, model folder, timers."""
import os
import sys
import time
from pathlib import Path

MODELS = Path(os.environ.get("JARVIS_VOICE_MODELS", r"C:\Users\felip\jarvis-voice-models"))
OUT = Path(os.environ.get("JARVIS_VOICE_OUT", r"C:\Users\felip\jarvis-voice-out"))
OUT.mkdir(parents=True, exist_ok=True)
SENTENCES = (
    "Bom dia, senhor. Em que posso ser útil?",
    "O senhor tem três tarefas hoje, e a primeira é a landing do Dindin.",
    "Terminou tudo antes do previsto. Isso é suspeito, mas aceito os elogios.",
)


def read_env(name: str) -> str:
    """A value from the repo's .env (or the environment). The file stays out of git; the key is never printed."""
    if os.environ.get(name):
        return os.environ[name]
    env = Path(__file__).resolve().parents[2] / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    raise SystemExit(f"{name} não encontrada em {env}")


def add_cuda_dlls() -> None:
    """faster-whisper needs cuBLAS and cuDNN; pip ships them inside site-packages/nvidia/*/bin."""
    if sys.platform != "win32":
        return
    import site
    for base in site.getsitepackages():
        for sub in (Path(base) / "nvidia").glob("*/bin"):
            os.add_dll_directory(str(sub))
            os.environ["PATH"] = str(sub) + os.pathsep + os.environ["PATH"]


class Timer:
    def __init__(self, label: str) -> None:
        self.label = label

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc) -> None:
        self.seconds = time.perf_counter() - self.start
        print(f"  {self.label}: {self.seconds * 1000:.0f} ms")
