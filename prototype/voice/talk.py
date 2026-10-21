"""Stage 2 of the voice prototype: hands-free conversation where the owner can interrupt the Jarvis.

    microphone (always open) -> Silero VAD -> faster-whisper (GPU) -> Groq (persona/jarvis.md) -> Edge-TTS -> speaker

Enter opens the conversation; then just talk (no need to call him). While he is speaking, only calling him cuts him:
say "Jarvis" (or "Jarvis, ..." with the new request) and he stops at once; anything else said over him only lowers his
volume for a moment and he goes on. "Tchau" (or 20 s of silence) ends it. Use headphones.

Run in the Windows venv:
    python talk.py                          Logitech microphone, default output
    python talk.py --mic Logitech --out Realtek   pick devices by a part of their name
    python talk.py --list                   list the audio devices
    python talk.py --simulate               no devices: synthetic voices play the owner (proves the interruption)
    python talk.py --save-audio             also keep each thing you say as a WAV in the output folder (local only),
                                            so bench_clips.py can compare Whisper models on your real voice
"""
import argparse
import asyncio
import csv
import io
import queue
import re
import sys
import threading
import time
from datetime import datetime

import numpy as np
import sounddevice as sd
import soundfile as sf

from common import OUT, add_cuda_dlls, read_env
from duplex import FOLLOW_UP_S, FRAME, fold, IDLE_S, RATE, Conversation, Player, SpeechGate, StreamingVad
from turn_loop import SRC, VOICE, VOICE_RULES, clean, cut, load, load_template, pick_mic, polish, render, stream_groq
from turn_loop import for_speech, is_greeting, starts_with_greeting


PURE_GREETING = re.compile(r"^\W*(?:bom dia|boa tarde|boa noite)\W*(?:senhor)?\W*$")
VOICE_OVERRIDE = (
    "\n\nNeste canal o senhor quer OUVIR você: ignore qualquer regra de mandar detalhe por texto. Você não tem como "
    "enviar mensagem, Telegram, lembrete ou qualquer coisa por aqui, então NUNCA prometa enviar ou fazer algo que "
    "exija ferramenta. Para um pedido que pede explicação longa, dê o essencial em 3 a 5 frases curtas faladas e "
    "pergunte se ele quer que você continue."
)


def pick_output(fragment: str | None):
    if not fragment:
        return None
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0 and fragment.lower() in d["name"].lower():
            return i
    print(f"saída '{fragment}' não encontrada: usando a padrão")
    return None


def synth_owner(text: str) -> np.ndarray:
    """A sentence in another Edge voice (a woman's), as 16 kHz mono audio: stands in for the owner talking."""
    import edge_tts

    async def go() -> bytes:
        data = bytearray()
        async for chunk in edge_tts.Communicate(text, "pt-BR-FranciscaNeural").stream():
            if chunk["type"] == "audio":
                data += chunk["data"]
        return bytes(data)

    audio, rate = sf.read(io.BytesIO(asyncio.run(go())), dtype="float32")
    audio = audio.mean(axis=1) if audio.ndim > 1 else audio
    return np.interp(np.linspace(0, len(audio), int(len(audio) * RATE / rate), endpoint=False),
                     np.arange(len(audio)), audio).astype(np.float32)


def simulate(conversation: Conversation, blocks: queue.Queue, player: Player, stamp) -> None:
    """Script: ask something long, wait until the Jarvis is talking, talk over him, then say goodbye."""
    first = synth_owner("Jarvis, me explica em detalhes como funciona o Firebase, com todos os produtos.")
    distractor = synth_owner("Pera aí, deixa eu ver uma coisa aqui, só um minuto.")
    named = synth_owner("Jarvis, na verdade me fala só do Supabase.")
    bye = synth_owner("Jarvis, tchau.")
    def feed(audio: np.ndarray) -> None:
        for i in range(0, len(audio) - FRAME + 1, FRAME):
            blocks.put(audio[i:i + FRAME])
            time.sleep(FRAME / RATE)

    def silence(seconds: float) -> None:
        feed(np.zeros(int(seconds * RATE), dtype=np.float32))

    def owner() -> None:
        silence(1.0)
        stamp("DONO: fala a 1ª frase")
        feed(first)
        silence(0.5)
        while not player.heard():  # the Jarvis has not started to talk yet
            silence(0.1)
        silence(1.5)  # let him talk a little
        stamp("DONO: fala por cima SEM chamar o Jarvis (deve ser ignorado)")
        feed(distractor)
        silence(2.0)
        stamp("DONO: chama 'Jarvis' por cima (deve cortar)")
        feed(named)
        silence(1.0)
        while not player.heard():
            silence(0.1)
        silence(2.5)
        stamp("DONO: 'Jarvis, tchau' (corta e encerra)")
        feed(bye)
        silence(3.0)

    threading.Thread(target=owner, daemon=True).start()
    conversation.run()
    print(f"interrupções: {conversation.interruptions} | vozes ignoradas: {conversation.ignored}")
    for message in conversation.history:
        print(f"  {message['role']}: {message['content'][:160]}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--mic", default="Logitech")
    parser.add_argument("--out", default=None)
    parser.add_argument("--idle", type=float, default=IDLE_S)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--save-audio", action="store_true")
    args = parser.parse_args()
    if args.list:
        for i, d in enumerate(sd.query_devices()):
            print(i, d["name"], f"in={d['max_input_channels']} out={d['max_output_channels']}")
        return

    key = read_env("GROQ_API_KEY")
    template = load_template(SRC / "persona" / "jarvis.md")
    table = load(SRC / "persona" / "pronuncias.json")
    mic = pick_mic(args.mic)
    out = pick_output(args.out)
    print(f"microfone: {sd.query_devices(mic)['name'] if mic is not None else 'padrão do sistema'}")
    print(f"saída: {sd.query_devices(out)['name'] if out is not None else 'padrão do sistema'}")

    add_cuda_dlls()
    from faster_whisper import WhisperModel
    print("carregando o Whisper e aquecendo a GPU (uns segundos na primeira vez)...")
    whisper = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")
    list(whisper.transcribe(np.zeros(RATE, dtype=np.float32), language="pt")[0])
    vad = StreamingVad()
    simulated = args.simulate
    t_zero = time.perf_counter()

    class FakeSpeaker:
        """Pulls the player at real-time pace, like a sound card would, without any device."""
        def __init__(self, rate, callback):
            self._alive = True
            def pull():
                buffer = np.zeros((1024, 1), dtype=np.float32)
                while self._alive:
                    callback(buffer, 1024, None, None)
                    time.sleep(1024 / rate)
            threading.Thread(target=pull, daemon=True).start()
        def stop(self): self._alive = False
        def close(self): self._alive = False

    player = Player(open_stream=lambda rate, cb, dev: FakeSpeaker(rate, cb)) if simulated else Player(device=out)

    def stamp(message: str) -> None:
        print(f"[{time.perf_counter() - t_zero:5.1f}s] {message}" if simulated else message)

    clips = {"n": 0}

    def save_clip(audio: np.ndarray, quick: bool, text: str, seconds: float) -> None:
        """Keep what the microphone heard, with what Whisper wrote, to compare models later (never leaves the PC)."""
        folder = OUT / "clips"
        folder.mkdir(exist_ok=True)
        clips["n"] += 1
        name = f"{datetime.now():%Y%m%d-%H%M%S}-{clips['n']:03d}{'-checagem' if quick else ''}.wav"
        sf.write(folder / name, audio, RATE)
        with open(folder / "clips.csv", "a", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow([name, "checagem" if quick else "frase", f"{seconds:.2f}", text])

    def transcribe(audio: np.ndarray, quick: bool = False) -> str:
        """`quick` is the "was that his name?" check: a few words are enough, so the output is capped (an unbounded
        decode of an odd chunk once took 6 s while he kept talking)."""
        started = time.perf_counter()
        # No vocabulary prompt in the check: on a chunk with little speech Whisper repeats the prompt back, and a prompt
        # that contains "Jarvis" would then "hear" his name in silence (a false interruption).
        extra = ({"max_new_tokens": 24, "without_timestamps": True} if quick
                 else {"initial_prompt": "Jarvis, Dindin, Firebase, Mind, Groq, Telegram."})
        segments, _ = whisper.transcribe(audio, language="pt", beam_size=1, vad_filter=False,
                                         condition_on_previous_text=False, **extra)
        text = " ".join(s.text.strip() for s in segments)
        if args.save_audio and not args.simulate:  # synthetic voices must never end up among the owner's clips
            save_clip(audio, quick, text, time.perf_counter() - started)
        print(f"  [Whisper{' (checagem)' if quick else ''} {time.perf_counter() - started:.2f} s, {len(audio) / RATE:.1f} s de áudio]"
              + f" «{text}»")
        return text

    # --- thinking and speaking, cancellable ---------------------------------------------------------------
    def start_speech(heard: str, history: list[dict], speech, player: Player) -> None:
        texts: queue.Queue = queue.Queue()
        t0 = time.perf_counter()
        first = {"sound": None, "token": None, "sentence": None, "synth": None}

        def tidy(sentence: str) -> str:
            sentence = clean(sentence)
            if not sentence:
                return ""
            sentence = polish(heard, sentence, datetime.now(), is_greeting=is_greeting(heard),
                              greeting_request=starts_with_greeting(heard), allows_help=False)
            # the tone fixer sees one sentence at a time here, so a lone "Bom dia, senhor." survives it: nobody greeted, drop it
            if not (is_greeting(heard) or starts_with_greeting(heard)) and PURE_GREETING.match(fold(sentence)):
                return ""
            return sentence

        def think() -> None:
            system = render(template, humor_allowed=True, now=datetime.now()) + VOICE_RULES + VOICE_OVERRIDE
            buffer, is_first = "", True
            try:
                stream = stream_groq(key, system, history)
                for piece in stream:
                    if speech.cancelled.is_set():
                        stream.close()
                        return
                    first["token"] = first["token"] or time.perf_counter() - t0
                    buffer += piece
                    sentences, buffer = cut(buffer, is_first)
                    for sentence in sentences:
                        is_first = False
                        if (sentence := tidy(sentence)):
                            first["sentence"] = first["sentence"] or time.perf_counter() - t0
                            speech.sentences.append(sentence)
                            texts.put((len(speech.sentences) - 1, sentence))
                if (tail := tidy(buffer)) and not speech.cancelled.is_set():
                    speech.sentences.append(tail)
                    texts.put((len(speech.sentences) - 1, tail))
            except Exception as exc:  # a network drop must not kill the conversation
                print(f"  (o modelo falhou: {type(exc).__name__})")
            finally:
                texts.put(None)

        def voice() -> None:
            import edge_tts

            async def one(sentence: str) -> bytes:
                data = bytearray()
                stream = edge_tts.Communicate(for_speech(sentence, table), VOICE).stream()
                try:
                    async for chunk in stream:
                        if speech.cancelled.is_set():
                            break
                        if chunk["type"] == "audio":
                            data += chunk["data"]
                finally:
                    await stream.aclose()  # a cut sentence must still close its connection
                return bytes(data)

            loop = asyncio.new_event_loop()
            try:
                while (item := texts.get()) is not None:
                    index, sentence = item
                    if speech.cancelled.is_set():
                        continue
                    try:
                        data = loop.run_until_complete(one(sentence))
                    except Exception as exc:
                        print(f"  (a voz falhou: {type(exc).__name__})")
                        continue
                    if speech.cancelled.is_set() or not data:
                        continue
                    audio, rate = sf.read(io.BytesIO(data), dtype="float32")
                    if first["sound"] is None:
                        first["sound"] = time.perf_counter() - t0
                        token, ready = first["token"] or 0.0, first["sentence"] or 0.0
                        print(f"  jarvis (1º som {first['sound']:.2f} s após a transcrição = 1º token do Groq {token:.2f} + "
                              f"1ª frase pronta +{ready - token:.2f} + voz Edge +{first['sound'] - ready:.2f}): {sentence}")
                    else:
                        print(f"  jarvis: {sentence}")
                    player.enqueue(index, audio, rate)
            finally:
                speech.generating = False

        threading.Thread(target=think, daemon=True).start()
        threading.Thread(target=voice, daemon=True).start()

    def say(text: str) -> None:
        """Speak one fixed line and wait for it (the goodbye)."""
        from duplex import Speech
        speech = Speech()
        speech.sentences.append(text)
        import edge_tts

        async def synth() -> bytes:
            data = bytearray()
            async for chunk in edge_tts.Communicate(text, VOICE).stream():
                if chunk["type"] == "audio":
                    data += chunk["data"]
            return bytes(data)

        audio, rate = sf.read(io.BytesIO(asyncio.run(synth())), dtype="float32")
        player.enqueue(0, audio, rate)
        while player.busy:
            time.sleep(0.05)
        time.sleep(0.3)

    ack_lines = ("Pois não, senhor?", "Sim, senhor?", "Às ordens, senhor.")
    ack_audio: list = []
    ack_next = {"i": 0}

    def prepare_acks() -> None:
        """Short lines synthesized once, so the answer to a bare "Jarvis" is instant (no network wait)."""
        import edge_tts

        async def synth(text: str) -> bytes:
            data = bytearray()
            async for chunk in edge_tts.Communicate(for_speech(text, table), VOICE).stream():
                if chunk["type"] == "audio":
                    data += chunk["data"]
            return bytes(data)

        for line in ack_lines:
            ack_audio.append(sf.read(io.BytesIO(asyncio.run(synth(line))), dtype="float32"))

    def ack() -> None:
        if not ack_audio:
            return
        audio, rate = ack_audio[ack_next["i"] % len(ack_audio)]
        ack_next["i"] += 1
        player.enqueue(9000 + ack_next["i"], audio, rate)

    prepare_acks()

    # --- the microphone: always open, 32 ms frames ----------------------------------------------------------
    blocks: queue.Queue = queue.Queue()

    def next_frame():
        try:
            return blocks.get(timeout=0.5)
        except queue.Empty:
            return None

    conversation = Conversation(next_frame, vad, SpeechGate(), player, transcribe, start_speech, say=say, ack=ack,
                                idle_s=args.idle, log=stamp)
    if simulated:
        simulate(conversation, blocks, player, stamp)
        return
    while True:
        if input("\nEnter para abrir a conversa (q + Enter sai): ").strip().lower() == "q":
            break
        print(f"  (ouvindo; sem o nome só até {FOLLOW_UP_S:.0f} s depois que ele termina de falar; depois, e pra interromper, "
              f"chame 'Jarvis'; diga 'tchau' ou fique {args.idle:.0f} s em silêncio pra encerrar)")
        vad.reset()
        while not blocks.empty():
            blocks.get_nowait()
        with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=FRAME, device=mic,
                            callback=lambda data, *_: blocks.put(data[:, 0].copy())):
            conversation.run()
        player.close()


if __name__ == "__main__":
    main()
