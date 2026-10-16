# Ambiente de voz (Windows) — como instalar do zero

O cliente de voz roda no **Python do Windows** (microfone e caixa estão lá); o núcleo do Jarvis fica no WSL. Este passo a passo refaz o ambiente numa máquina nova. Tudo local e grátis.

## Requisitos
- Windows 11 com WSL2, Python 3.12 do Windows (`py -0p` lista), driver NVIDIA recente (a RTX 3050 de 6 GB serve; `nvidia-smi` tem que funcionar).
- ~5 GB livres no `C:` (venv ~2,5 GB, modelos ~0,4 GB, cache do Whisper ~1,6 GB).

## 1. Ambiente virtual (PowerShell)
Fora do WSL e fora do repo, no disco do Windows (rápido, e o repo mora em `\\wsl.localhost`):

```powershell
python -m venv C:\Users\felip\jarvis-voice-venv
C:\Users\felip\jarvis-voice-venv\Scripts\python.exe -m pip install --upgrade pip
C:\Users\felip\jarvis-voice-venv\Scripts\python.exe -m pip install sounddevice numpy soundfile requests faster-whisper nvidia-cublas-cu12 nvidia-cudnn-cu12 kokoro-onnx piper-tts
```

`nvidia-cublas-cu12` e `nvidia-cudnn-cu12` trazem as DLLs de CUDA que o faster-whisper precisa (não precisa instalar o CUDA Toolkit); `common.py` as coloca no caminho.

## 2. Modelos de voz
Pasta: `C:\Users\felip\jarvis-voice-models` (no WSL: `/mnt/c/Users/felip/jarvis-voice-models`).

- **Kokoro** (de `thewh1teagle/kokoro-onnx`, release `model-files-v1.0`): `kokoro-v1.0.onnx` (~310 MB) e `voices-v1.0.bin` (~27 MB). No WSL:
  ```bash
  curl -L -o /mnt/c/Users/felip/jarvis-voice-models/kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
  curl -L -o /mnt/c/Users/felip/jarvis-voice-models/voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
  ```
  No PowerShell o mesmo vale com `curl.exe` e caminhos com barra invertida (no bash do WSL as barras invertidas se perdem).
- **Piper** (`pt_BR-faber-medium.onnx` e `.onnx.json`): copiados de `joee/training/piper_voices/`; também saem do repo `rhasspy/piper-voices` (Hugging Face), pasta `pt/pt_BR/faber/medium`.
- **Whisper** (`large-v3-turbo`): baixa sozinho na primeira execução do `bench_stt.py` (cache do Hugging Face, ~1,6 GB).

## 3. Rodar (a partir de qualquer terminal)
```powershell
cd \\wsl.localhost\Ubuntu\home\felip\projetos\jarvis\prototype\voice
C:\Users\felip\jarvis-voice-venv\Scripts\python.exe bench_tts.py --play
C:\Users\felip\jarvis-voice-venv\Scripts\python.exe bench_stt.py
```
Do WSL: `powershell.exe -NoProfile -Command "& 'C:\Users\felip\jarvis-voice-venv\Scripts\python.exe' bench_tts.py"`. Os WAVs saem em `C:\Users\felip\jarvis-voice-out`.

## Dispositivos de áudio (esta máquina, 2026-10-15)
Microfones: Logitech USB Microphone (dedicado), Intel Smart Sound (do notebook). Caixa: Realtek. Fone Bluetooth QCY evitado nos testes (microfone ruim e latência na troca de perfil).

## Armadilhas já vistas
- Copiar comando de `curl.exe ... C:\Users\...` pro **bash do WSL** perde as barras invertidas e dá "Permission denied": no WSL use `/mnt/c/...`.
- No PowerShell, `curl` puro é outro comando (alias de `Invoke-WebRequest`): use `curl.exe`.
- `nvidia-smi` dentro do WSL e no Windows enxergam a mesma GPU; os 6 GB são divididos entre Whisper e Kokoro.
