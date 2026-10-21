"""Stage 2 building blocks: listening while the Jarvis talks, so the owner can interrupt, but only by calling him:
"Jarvis" (like "Alexa") cuts the speech; anything else said over him is ignored and he keeps talking. No devices in
here (the microphone and the speaker are passed in), so the logic runs in tests.

    SpeechGate    frame probabilities -> "start" / "end" of a sentence (with a longer bar while the Jarvis speaks)
    StreamingVad  Silero VAD, one 32 ms frame at a time (the model that ships inside faster-whisper)
    Player        the speaker as a buffer that can be emptied at once (interruption), remembering what was heard
    Conversation  the loop that ties them: hear -> think -> speak, and cut the speech when the owner talks over it
"""
from __future__ import annotations

import collections
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

RATE = 16000
FRAME = 512                      # 32 ms at 16 kHz: what Silero expects
FRAME_S = FRAME / RATE
PRE_ROLL_S = 1.0                 # audio kept from before the "start" event, so the first word is never cut
MAX_SENTENCE_S = 30.0

START_S = 0.20                   # voice needed to start a sentence when the Jarvis is quiet
BARGE_IN_S = 0.40                # voice needed, while he talks, to even check for his name: a cough or "aham" is ignored
CHECK_FIRST_S = 1.2              # seconds of recording at which the first "was it his name?" check happens
CHECK_EVERY_S = 1.5              # and again every this many seconds while the voice goes on
MAX_CHECKS = 3
DUCK = 0.25                      # his volume while checking, so he does not talk full blast over the owner
SILENCE_S = 0.70                 # quiet that ends the sentence
IDLE_S = 20.0                    # no one talking for this long ends the conversation mode

EXIT_PHRASE = re.compile(r"^\W*(?:jarvis\W+)?(?:tchau|ate logo|ate mais|encerra\w*|chega por hoje|pode parar)\b")


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


_NAME = re.compile(r"\b(?:jarvis|jarves|jarvi|jarviz|jarvez|jarbis|jarvice|javis|garvis|charvis|harvis|jervis|ja vis|ja ves|ja vi)\b")
_NAME_AT_START = re.compile(r"^\W*(?:(?:ei|oi|ola|e|o|ow|opa|pera|peraí|pera ai|espera|calma)\W+)*(?:" + _NAME.pattern[2:-2] + r")\W*")


def has_name(text: str) -> bool:
    """Did the owner call him? Tolerant of how Whisper spells it."""
    return bool(_NAME.search(fold(text)))


def strip_name(text: str) -> str:
    """The sentence without the call at its start ("Jarvis, me fala do Supabase" -> "me fala do Supabase")."""
    folded = fold(text)
    match = _NAME_AT_START.match(folded)
    if match is None:
        return text.strip()
    # fold() keeps the length of ASCII text and only drops combining marks, so cut the original at the same word count
    words_removed = len(folded[:match.end()].split())
    return " ".join(text.split()[words_removed:]).strip(" ,.:;-!?")


def is_exit(text: str) -> bool:
    return bool(EXIT_PHRASE.match(fold(text)))


class StreamingVad:
    """Speech probability of each 32 ms frame; the model state is carried from one frame to the next."""

    def __init__(self, session=None) -> None:
        if session is None:
            from faster_whisper.vad import get_vad_model
            session = get_vad_model().session
        self._session = session
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, 64), dtype=np.float32)

    def prob(self, frame: np.ndarray) -> float:
        x = np.concatenate([self._context, frame.reshape(1, -1)], axis=1).astype(np.float32)
        out, self._h, self._c = self._session.run(None, {"input": x, "h": self._h, "c": self._c})
        self._context = x[:, -64:]
        return float(np.asarray(out).reshape(-1)[0])


class SpeechGate:
    """Frame probabilities in, "start" and "end" events out. Voice builds up a run that decays on quiet frames, so a
    dip inside a word does not reset it; the sentence ends after `silence_s` without voice."""

    def __init__(self, min_speech_s: float = START_S, silence_s: float = SILENCE_S, on: float = 0.5, off: float = 0.35) -> None:
        self.min_speech_s, self.silence_s, self._on, self._off = min_speech_s, silence_s, on, off
        self.active = False
        self._run = 0.0
        self._quiet = 0.0

    def feed(self, prob: float) -> str | None:
        if not self.active:
            self._run = self._run + FRAME_S if prob >= self._on else max(0.0, self._run - FRAME_S)
            if self._run >= self.min_speech_s:
                self.active, self._quiet = True, 0.0
                return "start"
            return None
        self._quiet = 0.0 if prob >= self._off else self._quiet + FRAME_S
        if self._quiet >= self.silence_s:
            self.active, self._run = False, 0.0
            return "end"
        return None

    def reset(self) -> None:
        self.active, self._run, self._quiet = False, 0.0, 0.0


class Player:
    """The speaker. Audio is queued as sentences; `stop()` drops everything not yet played at once."""

    def __init__(self, open_stream: Callable | None = None, device=None) -> None:
        self._open = open_stream or self._open_sounddevice
        self._device = device
        self._lock = threading.Lock()
        self._chunks: collections.deque = collections.deque()  # [sentence id, samples, offset]
        self._started: list[int] = []
        self._stream = None
        self._volume = 1.0
        self.rate = 0

    def _open_sounddevice(self, rate: int, callback, device):
        import sounddevice as sd
        stream = sd.OutputStream(samplerate=rate, channels=1, dtype="float32", callback=callback, device=device, blocksize=1024)
        stream.start()
        return stream

    def enqueue(self, sentence_id: int, audio: np.ndarray, rate: int) -> None:
        if self._stream is None:
            self.rate = rate
            self._stream = self._open(rate, self._callback, self._device)
        if rate != self.rate:  # every chunk of one voice has the same rate; resample defensively
            audio = np.interp(np.linspace(0, len(audio), int(len(audio) * self.rate / rate), endpoint=False),
                              np.arange(len(audio)), audio).astype(np.float32)
        with self._lock:
            self._chunks.append([sentence_id, np.asarray(audio, dtype=np.float32), 0])

    def _callback(self, outdata, frames, time_info, status) -> None:
        out = np.zeros(frames, dtype=np.float32)
        filled = 0
        with self._lock:
            while filled < frames and self._chunks:
                chunk = self._chunks[0]
                if chunk[0] not in self._started:
                    self._started.append(chunk[0])
                take = min(frames - filled, len(chunk[1]) - chunk[2])
                out[filled:filled + take] = chunk[1][chunk[2]:chunk[2] + take]
                filled += take
                chunk[2] += take
                if chunk[2] >= len(chunk[1]):
                    self._chunks.popleft()
        outdata[:, 0] = out * self._volume

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))

    @property
    def busy(self) -> bool:
        with self._lock:
            return bool(self._chunks)

    def stop(self) -> None:
        with self._lock:
            self._chunks.clear()

    def heard(self) -> list[int]:
        """Ids of the sentences that started playing (at least partly) since the last `reset_heard`."""
        with self._lock:
            return list(self._started)

    def reset_heard(self) -> None:
        with self._lock:
            self._started.clear()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


@dataclass
class Speech:
    """One answer being thought and spoken. `sentences` fills while the model writes; `cancel` stops everything."""
    sentences: list[str] = field(default_factory=list)
    cancelled: threading.Event = field(default_factory=threading.Event)
    generating: bool = True


class Conversation:
    """The hands-free loop. `frames` yields 32 ms microphone frames (or None on a timeout tick); `transcribe` turns
    audio into text; `start_speech(heard, history, speech, player)` thinks and speaks in background threads, filling
    `speech.sentences`, putting each sentence's audio in the player and setting `speech.generating` to False at the end.

    While the conversation is open the owner talks without calling him. Only while he is speaking does a voice need to
    say his name: the voice ducks his volume, a short transcription checks for the name, and the speech is cut if it is
    there; otherwise the volume comes back and he goes on."""

    def __init__(self, frames: Callable[[], np.ndarray | None], vad, gate: SpeechGate, player: Player,
                 transcribe: Callable[..., str], start_speech: Callable, say: Callable[[str], None] | None = None,
                 clock: Callable[[], float] = time.perf_counter, idle_s: float = IDLE_S, log: Callable[[str], None] = print) -> None:
        self._frames, self._vad, self._gate, self._player = frames, vad, gate, player
        self._transcribe, self._start_speech, self._say = transcribe, start_speech, say
        self._clock, self._idle_s, self._log = clock, idle_s, log
        self.history: list[dict] = []
        self._ring: collections.deque = collections.deque(maxlen=int(PRE_ROLL_S / FRAME_S))
        self._recording: list[np.ndarray] | None = None
        self._speech: Speech | None = None
        self._checking = False        # a voice started over the Jarvis and has not been identified yet
        self._named = False           # ...and it called him
        self._checks = 0
        self._next_check = CHECK_FIRST_S
        self.interruptions = 0
        self.ignored = 0              # voices over him that did not call him

    def _speaking(self) -> bool:
        return self._speech is not None and (self._speech.generating or self._player.busy)

    def _commit_answer(self) -> None:
        """Put in the history what the Jarvis said: all of it, or only what the owner heard before cutting in."""
        speech = self._speech
        self._speech = None
        if speech is None:
            return
        heard = self._player.heard()
        said = [speech.sentences[i] for i in heard if i < len(speech.sentences)]
        if not said:
            return
        interrupted = speech.cancelled.is_set()
        self.history.append({"role": "assistant", "content": " ".join(said) + (" [o senhor interrompeu]" if interrupted else "")})

    def _cut(self) -> None:
        if self._speech is not None:
            self._speech.cancelled.set()
        self._player.stop()
        self._player.set_volume(1.0)
        self._commit_answer()
        self.interruptions += 1
        self._named = True
        self._log("  (interrompido)")

    def _drop_check(self) -> None:
        """The voice over him did not call him: forget it and give him back his volume."""
        self._recording, self._checking, self._named = None, False, False
        self._player.set_volume(1.0)
        self.ignored += 1
        self._log("  (voz sem o meu nome: ignorada)")

    def _check_name(self) -> None:
        self._checks += 1
        text = self._transcribe(np.concatenate(self._recording), quick=True)
        if has_name(text):
            self._cut()
        elif self._checks >= MAX_CHECKS:
            self._drop_check()
        else:
            self._next_check += CHECK_EVERY_S

    def _turn(self, heard: str) -> bool:
        """Answer what the owner said. False when he asked to end the conversation."""
        heard = strip_name(heard) if has_name(heard) else heard.strip()
        if len(heard) < 2:
            return True  # he only called ("Jarvis"): the next sentence is the turn
        self._log(f"  você: {heard}")
        if is_exit(heard):
            if self._say:
                self._say("Até logo, senhor.")
            return False
        self.history.append({"role": "user", "content": heard})
        self._player.reset_heard()
        self._speech = Speech()
        self._start_speech(heard, self.history[-12:], self._speech, self._player)
        return True

    def _finish(self, audio: np.ndarray) -> bool:
        """The owner stopped talking. Returns False to end the conversation."""
        checking, named = self._checking, self._named
        self._checking, self._named = False, False
        heard = self._transcribe(audio).strip()
        if checking and not named:
            if self._speaking():
                if not has_name(heard):  # he talked over, never called him: ignored
                    self._player.set_volume(1.0)
                    self.ignored += 1
                    self._log("  (voz sem o meu nome: ignorada)")
                    return True
                self._cut()
            else:
                self._player.set_volume(1.0)  # he finished meanwhile: the open conversation takes it as a turn
        return self._turn(heard)

    def run(self) -> None:
        last_activity = self._clock()
        while True:
            frame = self._frames()
            now = self._clock()
            if frame is None:
                if not self._speaking() and self._recording is None and now - last_activity > self._idle_s:
                    self._log("  (silêncio: encerrando o modo conversa)")
                    return
                continue
            if self._speech is not None and not self._speaking():
                self._commit_answer()
            speaking = self._speaking()
            self._gate.min_speech_s = BARGE_IN_S if speaking else START_S
            event = self._gate.feed(self._vad.prob(frame))
            self._ring.append(frame)
            if self._recording is not None:
                self._recording.append(frame)
                if len(self._recording) * FRAME_S > MAX_SENTENCE_S:
                    event = "end"
            if self._gate.active or speaking:
                last_activity = now
            if event == "start":
                self._recording = list(self._ring)
                if speaking:
                    self._checking, self._named, self._checks, self._next_check = True, False, 0, CHECK_FIRST_S
                    self._player.set_volume(DUCK)
            elif event == "end" and self._recording is not None:
                audio, self._recording = np.concatenate(self._recording), None
                self._gate.reset()
                if not self._finish(audio):
                    return
                last_activity = self._clock()
            if (self._recording is not None and self._checking and not self._named
                    and len(self._recording) * FRAME_S >= self._next_check):
                if self._speaking():
                    self._check_name()
                else:  # he stopped talking while the voice went on: nothing to protect any more
                    self._player.set_volume(1.0)
                    self._checking = False
