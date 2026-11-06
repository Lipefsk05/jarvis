"""Stage 1 of the voice prototype: one turn at a time. Press Enter, speak, and when you stop the Jarvis answers aloud.

    microphone -> energy VAD -> faster-whisper (GPU) -> Groq (persona/jarvis.md) -> Edge-TTS voice

The answer is spoken sentence by sentence: the first sentence plays while the next ones are still being made.
Every turn prints its timings (and appends them to turnos.csv in the output folder).

Run in the Windows venv:
    python turn_loop.py                  talk with the microphone (Enter to talk, q to quit)
    python turn_loop.py --mic Logitech   pick the input device by a part of its name (default: Logitech, else system default)
    python turn_loop.py --text "bom dia" skip microphone and Whisper: only the model and the voice
    python turn_loop.py --wav fala.wav   skip the microphone: transcribe a recording, answer it
"""
import argparse
import asyncio
import csv
import io
import json
import queue
import re
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

from common import OUT, add_cuda_dlls, read_env

SRC = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC / "src"))
# stdlib-only modules of the core, imported without installing it: the same persona, tone fixes and pronunciation as Telegram
from jarvis.persona import load_template, render  # noqa: E402
from jarvis.pronunciation import for_speech, load  # noqa: E402
from jarvis.style import is_greeting, starts_with_greeting  # noqa: E402
from jarvis.tone import polish  # noqa: E402

RATE = 16000
BLOCK = RATE // 10                      # 100 ms
SILENCE_END = 0.9                       # seconds of quiet that end the sentence
GIVE_UP_AFTER = 8.0                     # seconds without speech
MAX_SECONDS = 30.0
VOICE = "pt-BR-AntonioNeural"
GROQ_MODEL = "openai/gpt-oss-120b"
VOICE_RULES = (
    "\n\n## Canal: VOZ (protótipo)\n"
    "O senhor está falando com você pelo microfone e você responde em voz alta. Neste canal você NÃO tem ferramentas: "
    "só conversa. Responda em 1 a 3 frases curtas e faladas, sem listas, sem markdown, sem emojis e sem 'dois pontos' "
    "no meio da frase. Se a resposta precisaria de uma lista ou de detalhe longo, diga que manda por texto no Telegram."
)


# --- listening ----------------------------------------------------------------------------------------

def pick_mic(fragment: str):
    devices = [(i, d) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
    for i, d in devices:
        if fragment.lower() in d["name"].lower():
            return i
    return None


def listen(device) -> np.ndarray | None:
    """Record from the first sound until `SILENCE_END` of quiet. None if nothing was said."""
    blocks: queue.Queue = queue.Queue()
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK, device=device,
                        callback=lambda data, *_: blocks.put(data[:, 0].copy())):
        ambient = np.concatenate([blocks.get() for _ in range(4)])  # 0.4 s of the room before speaking
        threshold = max(0.012, 3 * float(np.sqrt(np.mean(ambient ** 2))))
        print("  (ouvindo...)")
        recorded, pre, started, quiet, began = [], [], False, 0.0, time.time()
        while True:
            block = blocks.get()
            loud = float(np.sqrt(np.mean(block ** 2))) > threshold
            if not started:
                pre = (pre + [block])[-3:]               # 0.3 s before the voice, so the first word is not cut
                if loud:
                    started, recorded, quiet = True, pre + [], 0.0
                elif time.time() - began > GIVE_UP_AFTER:
                    return None
                continue
            recorded.append(block)
            quiet = 0.0 if loud else quiet + BLOCK / RATE
            if quiet >= SILENCE_END or len(recorded) * BLOCK / RATE > MAX_SECONDS:
                return np.concatenate(recorded)


def load_wav(path: str) -> np.ndarray:
    audio, rate = sf.read(path, dtype="float32")
    audio = audio.mean(axis=1) if audio.ndim > 1 else audio
    if rate != RATE:
        audio = np.interp(np.linspace(0, len(audio), int(len(audio) * RATE / rate), endpoint=False),
                          np.arange(len(audio)), audio).astype(np.float32)
    return audio


# --- thinking and speaking, as a pipeline ------------------------------------------------------------------
# model (streaming) -> sentences -> voice (Edge-TTS) -> speaker. The first sentence is spoken while the model
# is still writing the rest.

def stream_groq(key: str, system: str, history: list[dict]):
    body = json.dumps({"model": GROQ_MODEL, "reasoning_effort": "low", "max_tokens": 700, "stream": True,
                       "messages": [{"role": "system", "content": system}] + history}).encode()
    request = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", body, {
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "jarvis-voice-prototype/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        for raw in response:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            delta = (json.loads(data)["choices"][0].get("delta") or {})
            if delta.get("content"):
                yield delta["content"]


def clean(text: str) -> str:
    """Plain spoken text: the joke mark opened, markdown and emoji gone."""
    text = text.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", ", ")
    text = re.sub(r"\[\[humor:\s*(.*?)\]\]", r"\1", text, flags=re.S)
    text = re.sub(r"\[\[.*?\]\]|[*_`#>]", "", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", "", text)
    return " ".join(text.split())


FIRST_CHUNK_CHARS = 55  # a first sentence longer than this is cut at its last comma, so the voice starts sooner


def cut(buffer: str, first: bool) -> tuple[list[str], str]:
    """Complete sentences at the start of `buffer`, and what is left. Never cuts inside an open [[...]] mark."""

    def closed(chunk: str) -> bool:
        """No [[...]] mark left open in `chunk`: only then is it safe to cut right after it."""
        return chunk.count("[[") <= chunk.count("]]")

    found: list[str] = []
    while closed(buffer):
        match = next((m for m in re.finditer(r"(?<=[.!?…])\s+", buffer) if closed(buffer[:m.start()])), None)
        comma = next((i for i in range(len(buffer) - 2, -1, -1) if buffer[i] == "," and closed(buffer[:i + 1])), None) \
            if first and len(buffer) > FIRST_CHUNK_CHARS else None
        if match:
            found.append(buffer[:match.start()])
            buffer, first = buffer[match.end():], False
        elif comma is not None:
            found.append(buffer[:comma + 1])
            buffer, first = buffer[comma + 1:].lstrip(), False
        else:
            break
    return found, buffer


def respond_aloud(key: str, system: str, history: list[dict], table: dict[str, str], done: float, heard: str) -> dict:
    """Think and speak at once. Returns the full reply and when things happened (seconds after `done`)."""
    texts: queue.Queue = queue.Queue()
    audios: queue.Queue = queue.Queue()
    result = {"reply": "", "llm_first": None, "first_sound": None}
    spoken: list[str] = []

    def tidy(sentence: str) -> str:
        """Same fixes as the Telegram replies: the greeting follows the clock, no reflex openers, no tacked-on offers."""
        sentence = clean(sentence)
        if not sentence:
            return ""
        return polish(heard, sentence, datetime.now(), is_greeting=is_greeting(heard),
                      greeting_request=starts_with_greeting(heard), allows_help=False)

    def think() -> None:
        buffer, first = "", True
        try:
            for piece in stream_groq(key, system, history):
                buffer += piece
                sentences, buffer = cut(buffer, first)
                for sentence in sentences:
                    first = False
                    sentence = tidy(sentence)
                    if sentence:
                        result["llm_first"] = result["llm_first"] or time.perf_counter() - done
                        spoken.append(sentence)
                        texts.put(sentence)
            tail = tidy(buffer)
            if tail:
                result["llm_first"] = result["llm_first"] or time.perf_counter() - done
                spoken.append(tail)
                texts.put(tail)
        finally:
            texts.put(None)

    def voice() -> None:
        import edge_tts

        async def one(sentence: str) -> bytes:
            buffer = bytearray()
            async for chunk in edge_tts.Communicate(for_speech(sentence, table), VOICE).stream():
                if chunk["type"] == "audio":
                    buffer += chunk["data"]
            return bytes(buffer)

        loop = asyncio.new_event_loop()
        try:
            while (sentence := texts.get()) is not None:
                audios.put(loop.run_until_complete(one(sentence)))
        finally:
            audios.put(None)

    threading.Thread(target=think, daemon=True).start()
    threading.Thread(target=voice, daemon=True).start()
    while (data := audios.get()) is not None:
        audio, rate = sf.read(io.BytesIO(data), dtype="float32")
        if result["first_sound"] is None:
            result["first_sound"] = time.perf_counter() - done
        sd.play(audio, rate)
        sd.wait()
    result["reply"] = " ".join(spoken)
    return result


# --- one turn -----------------------------------------------------------------------------------------

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # the old Windows console cannot print every character
    parser = argparse.ArgumentParser()
    parser.add_argument("--mic", default="Logitech")
    parser.add_argument("--text")
    parser.add_argument("--wav")
    args = parser.parse_args()

    key = read_env("GROQ_API_KEY")
    template = load_template(SRC / "persona" / "jarvis.md")
    table = load(SRC / "persona" / "pronuncias.json")
    history: list[dict] = []
    device = pick_mic(args.mic)
    print(f"microfone: {sd.query_devices(device)['name'] if device is not None else 'padrão do sistema'}")

    model = None
    if not args.text:
        add_cuda_dlls()
        from faster_whisper import WhisperModel
        print("carregando o Whisper e aquecendo a GPU (uns segundos na primeira vez)...")
        model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")
        list(model.transcribe(np.zeros(RATE, dtype=np.float32), language="pt")[0])

    log = OUT / "turnos.csv"
    new_log = not log.exists()
    once = bool(args.text or args.wav)
    while True:
        if args.text:
            heard, audio = args.text, None
        else:
            if args.wav:
                audio = load_wav(args.wav)
            else:
                if input("\nEnter para falar (q + Enter sai): ").strip().lower() == "q":
                    return
                audio = listen(device)
                if audio is None:
                    print("  não ouvi nada.")
                    continue
        done = time.perf_counter()                       # the person stopped talking
        stt = 0.0
        if audio is not None:
            segments, _ = model.transcribe(audio, language="pt", beam_size=1, vad_filter=False,
                                           initial_prompt="Jarvis, Dindin, Firebase, Mind, Groq, Telegram.")
            heard = " ".join(s.text.strip() for s in segments)
            stt = time.perf_counter() - done
            print(f"  você: {heard}  [{stt * 1000:.0f} ms]")
        if not heard.strip():
            print("  (nada entendido)")
            if once:
                return
            continue
        history.append({"role": "user", "content": heard})
        system = render(template, humor_allowed=True, now=datetime.now()) + VOICE_RULES
        got = respond_aloud(key, system, history[-12:], table, done, heard)
        reply, first = got["reply"], got["first_sound"] or 0.0
        history.append({"role": "assistant", "content": reply})
        print(f"  jarvis: {reply}")
        thought = (got["llm_first"] or 0.0) - stt
        print(f"  >>> do fim da sua fala ao primeiro som: {first:.2f} s "
              f"(Whisper {stt:.2f} + 1ª frase do modelo {thought:.2f} + voz {first - stt - thought:.2f})")
        with open(log, "a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if new_log:
                writer.writerow(["quando", "whisper_s", "modelo_1a_frase_s", "voz_s", "total_s", "ouvido", "resposta"])
                new_log = False
            writer.writerow([datetime.now().isoformat(timespec="seconds"), f"{stt:.2f}", f"{thought:.2f}",
                             f"{first - stt - thought:.2f}", f"{first:.2f}", heard, reply])
        if once:
            return


if __name__ == "__main__":
    main()
