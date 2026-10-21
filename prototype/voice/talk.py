"""Stage 2 of the voice prototype: hands-free conversation where the owner can interrupt the Jarvis.

    microphone (always open) -> Silero VAD -> faster-whisper (GPU) -> Groq (persona/jarvis.md) -> Edge-TTS -> speaker

Enter opens the conversation; then just talk (no need to call him). While he is speaking, only calling him cuts him:
say "Jarvis" (or "Jarvis, ..." with the new request) and he stops at once; anything else said over him only lowers his
volume for a moment and he goes on. "Tchau" (or 20 s of silence) ends it. Use headphones.

Run in the Windows venv:
    python talk.py                          Logitech microphone, default output
    python talk.py --mic Logitech --out Realtek   pick devices by a part of their name
    python talk.py --list                   list the audio devices
    python talk.py --standby                no Enter: the microphone stays open and saying "Jarvis" opens the conversation
                                            (what is said without his name is only checked, never answered; Ctrl+C exits)
    python talk.py --dev                    start in dev mode: the work happens in the Mind with the full Claude Code behind
                                            the Jarvis voice ("modo dev" / "modo casual" switch it by voice; dev.py explains)
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

import dev
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
    parser.add_argument("--standby", action="store_true")
    parser.add_argument("--dev", action="store_true", help="start in dev mode (otherwise say \"modo dev\")")
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
                 else {"initial_prompt": "Jarvis, Dindin, Firebase, Mind, Groq, Telegram, Duplex, Forge, Domo, MindView, modo dev, modo casual."})
        segments, _ = whisper.transcribe(audio, language="pt", beam_size=1, vad_filter=False,
                                         condition_on_previous_text=False, **extra)
        text = " ".join(s.text.strip() for s in segments)
        if args.save_audio and not args.simulate:  # synthetic voices must never end up among the owner's clips
            save_clip(audio, quick, text, time.perf_counter() - started)
        print(f"  [Whisper{' (checagem)' if quick else ''} {time.perf_counter() - started:.2f} s, {len(audio) / RATE:.1f} s de áudio]"
              + f" «{text}»")
        return text

    def speak(texts: queue.Queue, speech, player: Player, first: dict, t0: float) -> None:
        """Turn the sentences that arrive in `texts` ((index, text) pairs, None at the end) into sound, one by one."""
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
                conversation.note_spoken(sentence)
        finally:
            speech.generating = False
            try:  # an event loop left open prints "Task was destroyed but it is pending" when it is collected
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()
            except Exception:
                pass

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
            speak(texts, speech, player, first, t0)

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
        conversation.note_spoken(text)
        started = time.perf_counter()
        while player.busy and time.perf_counter() - started < 20:  # never block the conversation for ever on a stuck output
            time.sleep(0.05)
        if time.perf_counter() - started > 8:
            print(f"  (a fala «{text[:40]}» demorou {time.perf_counter() - started:.0f} s pra terminar)")
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

    # --- dev mode: "modo dev" on, "modo casual" off; the work happens in the Mind, the voice stays the Jarvis ---------
    dev.write_briefing()
    dev_settings = dev.Settings.load(OUT / "dev.json")
    dev_state = {"on": args.dev, "session": None, "extra": [], "pending": None}
    try:
        tg_token = read_env("TELEGRAM_BOT_TOKEN")
        tg_chat = read_env("TELEGRAM_ALLOWED_USER_IDS").split(",")[0].strip()
    except (SystemExit, OSError):
        tg_token = tg_chat = ""
    _NO, _ALWAYS = re.compile(r"\b(?:nao|negado|nega|recuso|cancela)\b"), re.compile(r"\bsempre\b")
    _YES = re.compile(r"\b(?:sim|pode|claro|autoriz\w+|libera\w*|vai|faz|manda|ok|beleza)\b")

    def permission_answer(text: str) -> str | None:
        """"yes" / "always" / "no" when a short sentence answers the permission question, else None."""
        folded = fold(text)
        if len(folded.split()) > 7:
            return None
        if _NO.search(folded):
            return "no"
        if _ALWAYS.search(folded):
            return "always"
        return "yes" if _YES.search(folded) else None

    def session_rule(denial: dict) -> str:
        """What to allow for the rest of this dev session after a "sim": the exact command, the exact file, or the tool."""
        tool, data = denial.get("tool_name", ""), denial.get("tool_input", {}) or {}
        if tool == "Bash":
            return f"Bash({str(data.get('command', '')).strip()})"
        if data.get("file_path"):
            return f"{tool}({data['file_path']})"
        return tool

    dev_jobs: list[dict] = []  # every job of this run: {"id", "label", "stop", "running", "muted", "session"}

    def speak_text(text: str, speech, player: Player) -> None:
        """Speak a finished line the background work announces by itself (nobody was talking when it came)."""
        texts: queue.Queue = queue.Queue()
        for index, sentence in enumerate(s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()):
            speech.sentences.append(sentence.strip())
            texts.put((index, sentence.strip()))
        texts.put(None)
        threading.Thread(target=speak, args=(texts, speech, player, {"sound": None, "token": None, "sentence": None},
                                             time.perf_counter()), daemon=True).start()

    def intercept(heard: str) -> bool:
        """Mode switches, dev settings and commands to the running work are the Jarvis's own business: they never reach it."""
        mode = dev.parse_mode(heard)
        if mode == "dev":
            dev_state["on"] = True
            say("Modo dev ligado, senhor.")
            return True
        if mode == "casual":
            for job in dev_jobs:
                job["stop"].set()  # leaving the mode ends the work too: nothing keeps running behind the owner's back
            dev_jobs.clear()
            dev_state.update(on=False, session=None, extra=[], pending=None)  # and forgets this session's permissions
            say("Voltando ao modo casual, senhor.")
            return True
        if not dev_state["on"]:
            return False
        running = [j for j in dev_jobs if j["running"]]
        command = dev.parse_job_command(heard)
        if command in ("stop", "stop_all", "status") and not running:
            say("Não tenho nada rodando no momento, senhor.")  # no point asking the work about it
            return True
        if command and running:
            if command == "stop_all":
                for job in running:
                    job["stop"].set()
                say("Parei tudo, senhor.")
            elif command == "stop":
                running[-1]["stop"].set()
                say("Parei esse trabalho, senhor.")
            elif command == "continue":
                running[-1]["resumed"] = True
                say("Sigo no trabalho e aviso quando houver novidade, senhor.")
            else:
                say(f"Ainda estou em: {running[-1]['label']}, senhor." if len(running) == 1
                    else f"Tenho {len(running)} trabalhos em andamento, senhor; o último é: {running[-1]['label']}.")
            return True
        setting = dev.parse_setting(heard)
        if setting is None:
            return False
        kind, argument = setting
        if kind == "ceiling_off":
            dev_settings.ceiling = False
            dev_settings.save()
            say("Teto desligado, senhor. Só paro se o senhor mandar.")
        elif kind == "ceiling_on":
            dev_settings.ceiling = True
            dev_settings.save()
            say(f"Teto de {dev_settings.ceiling_s / 60:.0f} minutos de volta, senhor.")
        elif kind == "list":
            say(dev_settings.listing())
        else:
            gone = dev_settings.revoke(argument)
            say(f"Retirei {len(gone)} autorização(ões), senhor." if gone else "Não achei essa autorização, senhor.")
        return True

    def start_dev(heard: str, speech, player: Player) -> None:
        """One sentence of the dev conversation. The work runs in the background and keeps running when the owner calls the
        Jarvis by name (that only hushes the voice): spoken lines fill the wait while he listens, and the result is
        announced by itself when it is ready. A sentence said while a job runs is a new job, in parallel."""
        texts: queue.Queue = queue.Queue()
        t0 = time.perf_counter()
        first = {"sound": None, "token": None, "sentence": None}
        prompt, preface, session = heard, "", None
        running = [j for j in dev_jobs if j["running"]]
        if not running:
            session = dev_state["session"]  # nobody working: the conversation goes on in the same session
        pending, dev_state["pending"] = dev_state["pending"], None
        if pending is not None:
            session = pending["session"]  # the answer belongs to the work that asked
            answer = permission_answer(heard)
            denial = pending["denial"]
            if answer in ("yes", "always"):
                rule = dev.rule_for(denial)
                dev_state["extra"].append(session_rule(denial))
                if answer == "always" and rule:
                    dev_settings.remember(rule)
                elif answer == "always":
                    preface = "Esse eu sempre vou perguntar, senhor; liberei só desta vez."
                prompt = "Autorizado, pode seguir com isso."
            elif answer == "no":
                prompt = "Não autorizado. Siga sem isso e me diga o que ficou de fora."
        if prompt is heard:
            prompt = dev.fix_names(heard)
        job = {"id": len(dev_jobs) + 1, "label": dev.label_for(heard), "stop": threading.Event(), "running": True,
               "resumed": False, "session": session}
        dev_jobs.append(job)
        speech.working = True  # the Conversation must not take its silence for "he finished talking"

        def alive() -> bool:
            return not speech.cancelled.is_set()  # False once the owner called the Jarvis by name or started another job

        def emit(text: str, chatter: bool = False) -> None:
            if alive():
                speech.chatter = chatter
                index = len(speech.sentences)
                speech.sentences.append(text)
                texts.put((index, text))
            elif not chatter or job["resumed"]:  # paused: only results and questions get through, by themselves, until "continua"
                conversation.announce((f"Sobre {job['label']}, senhor: " if not chatter and any(j["running"] for j in dev_jobs if j is not job) else "") + text)

        def work() -> None:
            last = {"line": None, "at": time.perf_counter()}
            done = threading.Event()
            lines: list[str] = []

            def say_progress(line: str) -> None:
                last.update(line=line, at=time.perf_counter())
                if alive() or job["resumed"]:
                    emit(line, chatter=True)

            def on_tool(name: str, data: dict) -> None:
                if time.perf_counter() - last["at"] < 8:
                    return  # at most one line per 8 s: the work should not turn into a running commentary
                if (line := dev.progress_line(name, data, last["line"])):
                    say_progress(line)

            def ticker() -> None:
                while not done.wait(2.0):
                    if time.perf_counter() - last["at"] > 15:
                        say_progress(dev.pick(dev.STILL, last["line"]))

            def finish_lines() -> None:
                """The final lines (result, question) are spoken together, as ordinary speech, or announced as one piece."""
                speech.working = False
                if alive():
                    for line in lines:
                        emit(line)
                elif lines:
                    emit(" ".join(lines))

            try:
                if preface:
                    lines.append(preface)
                say_progress(dev.pick(dev.THINKING, None))
                threading.Thread(target=ticker, daemon=True).start()
                result = dev.run_turn(prompt, session, dev_settings.tools(dev_state["extra"]),
                                      dev_settings.ceiling_s if dev_settings.ceiling else None, on_tool, job["stop"])
                done.set()
                if result.session_id:
                    dev_state["session"] = job["session"] = result.session_id
                print(f"  [trabalho {job['id']}: {result.seconds:.0f} s{', estourou o teto' if result.timed_out else ''}"
                      f"{', parado pelo senhor' if result.cancelled else ''}]")
                if result.cancelled:
                    return
                if result.timed_out:
                    lines.append("Isso passou do tempo que me dei, senhor. Se quiser que eu continue, é só dizer.")
                elif result.error and not result.text.strip():
                    print(f"  (o trabalho falhou: {result.error})")
                    lines.append("Tive um problema com isso, senhor.")
                else:
                    spoken, full = dev.split_reply(result.text)
                    # with a denial the explanation is only noise before the question: say nothing but the question
                    if not result.denials:
                        lines += [x.strip() for x in re.split(r"(?<=[.!?])\s+", dev.speakable(spoken, 5)) if x.strip()]
                    if tg_token and tg_chat and (full != spoken or len(full) > 700):
                        dev.send_telegram(tg_token, tg_chat, full)
                    if result.denials:
                        denial = result.denials[0]
                        kind = dev.classify(denial, dev.settings_rules("deny"), dev.settings_rules("ask"))
                        print(f"  [negado: {denial.get('tool_name')} {denial.get('tool_input')} -> {kind}]")
                        if kind == "deny":
                            lines.append(f"Esse está bloqueado nas suas configurações, senhor: {dev.describe(denial)}.")
                        elif kind == "ask":
                            lines.append("Esse pede a sua aprovação direta no terminal, senhor; por voz eu ainda não consigo.")
                            if tg_token and tg_chat:
                                dev.send_telegram(tg_token, tg_chat, "Preciso da sua aprovação para: " + str(denial.get("tool_input", {}).get("command", denial)))
                        else:
                            dev_state["pending"] = {"denial": denial, "session": job["session"]}
                            lines.append(f"Posso {dev.describe(denial)}, senhor?")  # the answers (sim / sempre / não) will be listed on screen
            except Exception as exc:  # the conversation must outlive any failure of the work
                print(f"  (erro no trabalho: {type(exc).__name__}: {exc})")
                lines.append("Tive um problema com isso, senhor.")
            finally:
                done.set()
                job["running"] = False
                if not job["stop"].is_set():
                    finish_lines()
                speech.working = False
                texts.put(None)

        threading.Thread(target=work, daemon=True).start()
        threading.Thread(target=speak, args=(texts, speech, player, first, t0), daemon=True).start()

    def route_speech(heard: str, history: list[dict], speech, player: Player) -> None:
        (start_dev(heard, speech, player) if dev_state["on"] else start_speech(heard, history, speech, player))


    # --- the microphone: always open, 32 ms frames ----------------------------------------------------------
    blocks: queue.Queue = queue.Queue()

    def next_frame():
        try:
            return blocks.get(timeout=0.5)
        except queue.Empty:
            return None

    conversation = Conversation(next_frame, vad, SpeechGate(), player, transcribe, route_speech, say=say, ack=ack,
                                idle_s=args.idle, log=stamp, standby=args.standby and not simulated, intercept=intercept,
                                speak_text=speak_text)
    if simulated:
        simulate(conversation, blocks, player, stamp)
        return
    if args.standby:
        print("\n  (em espera: o microfone fica aberto e só 'Jarvis' abre a conversa; Ctrl+C sai)")
        vad.reset()
        try:
            with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=FRAME, device=mic,
                                callback=lambda data, *_: blocks.put(data[:, 0].copy())):
                conversation.run()
        except KeyboardInterrupt:
            print("\n  (saindo)")
        player.close()
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
