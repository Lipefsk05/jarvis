"""Run with the Windows venv: python -m unittest test_duplex (needs numpy only; no microphone or speaker)."""
import threading
import unittest

import numpy as np

import duplex as d


def gate_run(probs, **kw):
    gate = d.SpeechGate(**kw)
    return [(i, e) for i, p in enumerate(probs) if (e := gate.feed(p))]


class GateTest(unittest.TestCase):
    def test_a_sentence_starts_after_enough_voice_and_ends_after_silence(self):
        frames_voice = int(0.2 / d.FRAME_S) + 1
        frames_quiet = int(0.7 / d.FRAME_S) + 1
        events = gate_run([0.9] * frames_voice + [0.0] * frames_quiet)
        self.assertEqual([e for _, e in events], ["start", "end"])

    def test_a_short_blip_never_starts(self):
        self.assertEqual(gate_run([0.9] * 3 + [0.0] * 40), [])  # ~0.1 s

    def test_the_barge_in_bar_is_higher(self):
        frames = int(0.3 / d.FRAME_S)
        self.assertEqual([e for _, e in gate_run([0.9] * frames + [0.0] * 40, min_speech_s=d.START_S)], ["start", "end"])
        self.assertEqual(gate_run([0.9] * frames + [0.0] * 40, min_speech_s=d.BARGE_IN_S), [])

    def test_a_dip_inside_a_word_does_not_end_it(self):
        probs = [0.9] * 10 + [0.1] * 3 + [0.9] * 10 + [0.0] * 30
        self.assertEqual([e for _, e in gate_run(probs)], ["start", "end"])


class FakeStream:
    def stop(self): pass
    def close(self): pass


class PlayerTest(unittest.TestCase):
    def make(self):
        return d.Player(open_stream=lambda rate, cb, dev: FakeStream())

    def pull(self, player, n):
        out = np.zeros((n, 1), dtype=np.float32)
        player._callback(out, n, None, None)
        return out[:, 0]

    def test_plays_in_order_and_remembers_which_sentences_started(self):
        p = self.make()
        p.enqueue(0, np.ones(100, dtype=np.float32), 24000)
        p.enqueue(1, np.full(100, 2, dtype=np.float32), 24000)
        self.assertEqual(self.pull(p, 50).tolist(), [1.0] * 50)
        self.assertEqual(p.heard(), [0])
        self.pull(p, 100)
        self.assertEqual(p.heard(), [0, 1])
        self.assertEqual(self.pull(p, 200).sum(), 50 * 2)  # the rest, then silence

    def test_stop_drops_everything_not_yet_played(self):
        p = self.make()
        p.enqueue(0, np.ones(1000, dtype=np.float32), 24000)
        self.pull(p, 10)
        p.stop()
        self.assertFalse(p.busy)
        self.assertEqual(self.pull(p, 10).sum(), 0)


class ExitTest(unittest.TestCase):
    def test_exit_phrases(self):
        for text in ("Tchau", "tchau, Jarvis", "Até logo!", "jarvis, encerra a conversa", "chega por hoje"):
            self.assertTrue(d.is_exit(text), text)
        for text in ("me explica o que é encerramento", "quanto custa o dólar", "não vou dizer tchau agora"):
            self.assertFalse(d.is_exit(text), text)


class FakeVad:
    """Reads a marker the test puts in each frame: 1.0 = voice, 0.0 = quiet."""
    def prob(self, frame): return float(frame[0])


def voice(): return np.ones(d.FRAME, dtype=np.float32)
def quiet(): return np.zeros(d.FRAME, dtype=np.float32)


class ConversationTest(unittest.TestCase):
    def build(self, script, speak_frames=0):
        """`script` is a list of frames; the conversation reads them one by one and stops when they run out."""
        frames = iter(script)
        self.said, self.started = [], []
        self.player = d.Player(open_stream=lambda rate, cb, dev: FakeStream())
        self.logs = []

        def next_frame():
            try:
                return next(frames)
            except StopIteration:
                raise SystemExit

        def transcribe(audio):
            return self.heard.pop(0)

        def start_speech(heard, history, speech, player):
            self.started.append(heard)
            speech.sentences.append(f"resposta a {heard}")
            player.enqueue(0, np.ones(24000, dtype=np.float32), 24000)  # 1 s of audio, never pulled unless the test does
            speech.generating = False

        self.conv = d.Conversation(next_frame, FakeVad(), d.SpeechGate(), self.player, transcribe, start_speech,
                                   say=self.said.append, idle_s=1e9, log=self.logs.append)

    def run_conv(self):
        try:
            self.conv.run()
        except SystemExit:
            pass

    def sentence(self, seconds=0.5):
        return [voice()] * int(seconds / d.FRAME_S) + [quiet()] * (int(d.SILENCE_S / d.FRAME_S) + 2)

    def test_a_spoken_sentence_is_answered(self):
        self.heard = ["bom dia"]
        self.build(self.sentence())
        self.run_conv()
        self.assertEqual(self.started, ["bom dia"])
        self.assertEqual(self.conv.history, [{"role": "user", "content": "bom dia"}])

    def test_talking_over_the_answer_cuts_it_and_starts_a_new_turn(self):
        self.heard = ["primeira", "segunda"]
        script = self.sentence()
        # the answer is playing (1 s queued): pull a little so the sentence counts as heard, then the owner talks over it
        self.build(script + [quiet()] * 3 + [voice()] * int(0.6 / d.FRAME_S) + [quiet()] * (int(d.SILENCE_S / d.FRAME_S) + 2))
        original = self.conv._frames
        count = {"n": 0}

        def frames():
            count["n"] += 1
            if count["n"] == len(script) + 1:  # right after the first turn started: the player pulls some audio
                self.player._callback(np.zeros((512, 1), dtype=np.float32), 512, None, None)
            return original()

        self.conv._frames = frames
        self.run_conv()
        self.assertEqual(self.started, ["primeira", "segunda"])
        self.assertEqual(self.conv.interruptions, 1)
        self.assertEqual(self.conv.history[1], {"role": "assistant", "content": "resposta a primeira [o senhor interrompeu]"})
        self.assertEqual(self.conv.history[2], {"role": "user", "content": "segunda"})

    def test_a_short_noise_while_speaking_does_not_cut(self):
        self.heard = ["primeira"]
        script = self.sentence() + [voice()] * 3 + [quiet()] * 20  # ~0.1 s of voice over the answer
        self.build(script)
        self.run_conv()
        self.assertEqual(self.conv.interruptions, 0)
        self.assertTrue(self.player.busy)

    def test_the_exit_phrase_says_goodbye_and_ends(self):
        self.heard = ["tchau"]
        self.build(self.sentence() + [quiet()] * 5)
        self.run_conv()
        self.assertEqual(self.said, ["Até logo, senhor."])
        self.assertEqual(self.started, [])

    def test_idle_for_too_long_ends_the_conversation(self):
        ticks = iter(range(100))
        conv = d.Conversation(lambda: None, FakeVad(), d.SpeechGate(), d.Player(open_stream=lambda r, c, dv: FakeStream()),
                              lambda a: "", lambda *a: None, clock=lambda: float(next(ticks)), idle_s=5, log=lambda m: None)
        conv.run()  # would loop forever if the idle timeout did not end it


if __name__ == "__main__":
    unittest.main()
