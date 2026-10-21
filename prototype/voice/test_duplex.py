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

    def test_the_volume_glides_instead_of_jumping(self):
        player = self.make()
        player.enqueue(0, np.ones(24000, dtype=np.float32), 24000)
        player.set_volume(0.25)
        out = np.zeros((1024, 1), dtype=np.float32)
        player._callback(out, 1024, None, None)
        self.assertEqual(out[0, 0], 1.0)  # starts from where it was
        self.assertGreater(out[-1, 0], 0.25)  # not there yet: 1024 frames at 24 kHz is shorter than the fade
        for _ in range(8):
            player._callback(out, 1024, None, None)
        self.assertAlmostEqual(float(out[-1, 0]), 0.25, places=3)  # and it arrives

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


class UnfinishedTest(unittest.TestCase):
    def test_sounds_unfinished(self):
        for text in ("Então, eu queria saber", "Eu estava pensando...", "O Firebase é.", "Eu acho que,", "Quero saber se"):
            self.assertTrue(d.looks_unfinished(text), text)

    def test_sounds_finished(self):
        for text in ("Me explica o Supabase.", "Quanto custa o dólar?", "Obrigado!", ""):
            self.assertFalse(d.looks_unfinished(text), text)


class HoldSecondsTest(unittest.TestCase):
    def test_a_hanging_fragment_gets_the_longer_wait(self):
        for text in ("Então...", "Deixa eu pensar…", "Hum", "Então eu"):
            self.assertEqual(d.hold_seconds(text), d.HOLD_LONG_S, text)

    def test_a_longer_unfinished_sentence_gets_the_short_wait(self):
        self.assertEqual(d.hold_seconds("Eu queria saber como funciona o"), d.HOLD_S)


class NameTest(unittest.TestCase):
    def test_the_name_in_the_ways_whisper_writes_it(self):
        for text in ("Jarvis", "jarvis, para", "Ei Jarvis!", "Jarves, espera", "já vis", "Pera aí, Jarvis"):
            self.assertTrue(d.has_name(text), text)
        for text in ("aham", "quanto custa o dólar", "o servidor caiu", "", "Já vi esse vídeo", "já vi, é de política"):
            self.assertFalse(d.has_name(text), text)  # "já vi" is common speech: it must never count as his name

    def test_mishearings_of_the_name_count_only_when_they_are_the_whole_utterance(self):
        for text in ("Gavis.", "Jams.", "Jerms", "Jabs", "Jens.", "Gervis.", "J'ai a vis. J'ai a vis.", "Ei, Jams"):
            self.assertTrue(d.has_name(text), text)
            self.assertEqual(d.strip_name(text), "", text)
        for text in ("O Jens me mandou um vídeo", "Jens, me explica o Firebase", "Tchau", "jams de música"):
            self.assertFalse(d.has_name(text), text)

    def test_the_call_is_cut_from_the_start_of_the_sentence(self):
        self.assertEqual(d.strip_name("Jarvis, me fala só do Supabase."), "me fala só do Supabase")
        self.assertEqual(d.strip_name("Ei, Jarvis: pera aí"), "pera aí")
        self.assertEqual(d.strip_name("Jarvis"), "")
        self.assertEqual(d.strip_name("me fala do Jarvis amanhã"), "me fala do Jarvis amanhã")  # not at the start: untouched


class FakeVad:
    """Reads a marker the test puts in each frame: 1.0 = voice, 0.0 = quiet."""
    def prob(self, frame): return float(frame[0])


def voice(): return np.ones(d.FRAME, dtype=np.float32)
def quiet(): return np.zeros(d.FRAME, dtype=np.float32)


def seconds_of(frame, seconds): return [frame()] * int(seconds / d.FRAME_S)


class ConversationTest(unittest.TestCase):
    def build(self, script, hook=None, standby=False, idle_s=1e9, intercept=None):
        """`script` is a list of frames; the conversation reads them one by one and stops when they run out.
        `hook(n, player)` runs before frame n (to play some audio, like a sound card would)."""
        frames = iter(script)
        self.now = 0.0
        self.said, self.started, self.logs, self.count, self.acks = [], [], [], 0, []
        self.player = d.Player(open_stream=lambda rate, cb, dev: FakeStream())

        def next_frame():
            self.count += 1
            self.now += d.FRAME_S  # a virtual clock: one frame is 32 ms
            if hook:
                hook(self.count, self.player)
            try:
                return next(frames)
            except StopIteration:
                raise SystemExit

        def transcribe(audio, quick=False):
            return self.heard.pop(0)

        def start_speech(heard, history, speech, player):
            self.started.append(heard)
            speech.sentences.append(f"resposta a {heard}")
            player.enqueue(0, np.ones(24000, dtype=np.float32), 24000)  # 1 s of audio, only played when a test pulls it
            speech.generating = False

        self.conv = d.Conversation(next_frame, FakeVad(), d.SpeechGate(), self.player, transcribe, start_speech,
                                   say=self.said.append, ack=lambda: self.acks.append(1), clock=lambda: self.now, idle_s=idle_s,
                                   log=self.logs.append, standby=standby, intercept=intercept)

    def run_conv(self):
        try:
            self.conv.run()
        except SystemExit:
            pass

    def sentence(self, seconds=0.5):
        return seconds_of(voice, seconds) + seconds_of(quiet, d.SILENCE_S + 0.1)

    def answer_started(self):
        """A hook: once the first answer exists, the sound card pulls a little of it, so it counts as heard."""
        def hook(n, player):
            if n == len(self.first_turn) + 2:
                player._callback(np.zeros((512, 1), dtype=np.float32), 512, None, None)
        return hook

    def over(self, seconds):
        return seconds_of(quiet, 0.1) + seconds_of(voice, seconds) + seconds_of(quiet, d.SILENCE_S + 0.1)

    def test_a_spoken_sentence_is_answered_without_calling_him(self):
        self.heard = ["Bom dia."]
        self.build(self.sentence())
        self.run_conv()
        self.assertEqual(self.started, ["Bom dia."])
        self.assertEqual(self.conv.history, [{"role": "user", "content": "Bom dia."}])

    def test_calling_his_name_over_the_answer_cuts_it_and_the_rest_is_the_next_turn(self):
        self.heard = ["Primeira.", "jarvis, me fala", "Jarvis, me fala só do Supabase."]
        self.first_turn = self.sentence()
        self.build(self.first_turn + self.over(2.0), hook=self.answer_started())
        self.run_conv()
        self.assertEqual(self.started, ["Primeira.", "me fala só do Supabase"])
        self.assertEqual(self.conv.interruptions, 1)
        self.assertEqual(self.conv.history[1], {"role": "assistant", "content": "resposta a Primeira. [o senhor interrompeu]"})
        self.assertEqual(self.conv.history[2], {"role": "user", "content": "me fala só do Supabase"})

    def test_a_voice_that_does_not_call_him_is_ignored_and_he_goes_on(self):
        self.heard = ["Primeira.", "pera aí, deixa eu ver", "pera aí, deixa eu ver uma coisa", "pera aí, deixa eu ver uma coisa aqui"]
        self.first_turn = self.sentence()
        self.build(self.first_turn + self.over(3.0), hook=self.answer_started())
        self.run_conv()
        self.assertEqual(self.started, ["Primeira."])
        self.assertEqual(self.conv.interruptions, 0)
        self.assertEqual(self.conv.ignored, 1)
        self.assertTrue(self.player.busy)
        self.assertEqual(self.player._volume, 1.0)  # his volume came back

    def test_his_volume_is_lowered_while_checking(self):
        self.heard = ["Primeira.", "não é comigo", "não é comigo, não", "não é comigo, não"]
        self.first_turn = self.sentence()
        seen = []
        hook = self.answer_started()

        def spy(n, player):
            hook(n, player)
            seen.append(player._volume)

        self.build(self.first_turn + self.over(1.6), hook=spy)
        self.run_conv()
        self.assertIn(d.DUCK, seen)
        self.assertEqual(seen[-1], 1.0)

    def test_a_short_blip_over_him_is_not_even_checked(self):
        self.heard = ["Primeira."]  # a second transcription would raise IndexError
        self.first_turn = self.sentence()
        self.build(self.first_turn + seconds_of(voice, 0.1) + seconds_of(quiet, 1.0), hook=self.answer_started())
        self.run_conv()
        self.assertEqual((self.conv.interruptions, self.conv.ignored), (0, 0))

    def test_only_his_name_cuts_and_waits_for_the_next_sentence(self):
        self.heard = ["Primeira.", "Jarvis", "Jarvis"]
        self.first_turn = self.sentence()
        self.build(self.first_turn + self.over(1.3), hook=self.answer_started())
        self.run_conv()
        self.assertEqual(self.started, ["Primeira."])
        self.assertEqual(self.conv.interruptions, 1)

    def test_if_he_finishes_by_himself_the_voice_over_him_is_a_normal_turn(self):
        self.heard = ["Primeira.", "E o Supabase?"]
        self.first_turn = self.sentence()
        hook = self.answer_started()

        def finishing(n, player):
            hook(n, player)
            if n == len(self.first_turn) + 12:  # while the owner talks: the sound card plays what is left
                player._callback(np.zeros((24000, 1), dtype=np.float32), 24000, None, None)

        self.build(self.first_turn + self.over(1.6), hook=finishing)
        self.run_conv()
        self.assertEqual(self.started, ["Primeira.", "E o Supabase?"])
        self.assertEqual(self.conv.interruptions, 0)

    def test_the_early_transcription_is_reused_when_he_said_nothing_after_it(self):
        self.heard = ["Bom dia."]  # a second transcription would raise IndexError
        self.build(self.sentence())
        self.run_conv()
        self.assertEqual(self.conv.early_hits, 1)
        self.assertEqual(self.started, ["Bom dia."])

    def test_a_sentence_that_sounds_unfinished_waits_a_little_and_then_answers_it(self):
        self.heard = ["Então, eu queria saber..."]
        self.build(self.sentence() + seconds_of(quiet, d.HOLD_LONG_S + 0.2))  # a trailing "..." waits longer
        self.run_conv()
        self.assertEqual(self.conv.holds, 1)
        self.assertEqual(self.started, ["Então, eu queria saber..."])

    def test_if_he_goes_on_after_a_thinking_pause_it_is_one_sentence(self):
        self.heard = ["Então, eu queria saber", "Então, eu queria saber como funciona o Supabase."]
        script = self.sentence() + seconds_of(quiet, 0.2) + seconds_of(voice, 0.8) + seconds_of(quiet, d.SILENCE_S + 0.1)
        self.build(script)
        self.run_conv()
        self.assertEqual(self.started, ["Então, eu queria saber como funciona o Supabase."])
        self.assertEqual(self.conv.history[0]["content"], "Então, eu queria saber como funciona o Supabase.")

    def test_the_wait_happens_only_once_per_sentence(self):
        self.heard = ["Então, eu queria saber", "Então, eu queria saber como funciona"]
        script = self.sentence() + seconds_of(quiet, 0.2) + seconds_of(voice, 0.8) + seconds_of(quiet, d.SILENCE_S + 0.1)
        self.build(script)
        self.run_conv()
        self.assertEqual(self.conv.holds, 1)
        self.assertEqual(self.started, ["Então, eu queria saber como funciona"])  # still unfinished, but no second wait

    def test_a_bare_call_is_answered_so_he_knows_he_is_heard(self):
        self.heard = ["Jarvis."]
        self.build(self.sentence())
        self.run_conv()
        self.assertEqual(self.acks, [1])
        self.assertEqual(self.started, [])

    def test_something_unintelligible_is_logged_and_does_not_answer(self):
        self.heard = ["."]
        self.build(self.sentence())
        self.run_conv()
        self.assertEqual((self.acks, self.started), ([], []))
        self.assertTrue(any("pouco pra responder" in m for m in self.logs))

    def playing(self):
        """A hook: the sound card plays whatever is queued, at real-time pace (768 samples per 32 ms frame)."""
        def hook(n, player):
            if player.busy:
                player._callback(np.zeros((768, 1), dtype=np.float32), 768, None, None)
        return hook

    def test_after_the_window_closes_a_sentence_without_his_name_is_ignored(self):
        self.heard = ["Bom dia."]
        self.build(seconds_of(quiet, d.FOLLOW_UP_S + 1.0) + self.sentence())
        self.run_conv()
        self.assertEqual(self.started, [])
        self.assertEqual(self.conv.out_of_window, 1)

    def test_after_the_window_closes_calling_him_works(self):
        self.heard = ["Jarvis, que horas são?"]
        self.build(seconds_of(quiet, d.FOLLOW_UP_S + 1.0) + self.sentence())
        self.run_conv()
        self.assertEqual(self.started, ["que horas são?"])

    def test_the_window_reopens_each_time_he_finishes_talking(self):
        self.heard = ["Primeira.", "Segunda.", "Terceira."]
        script = (self.sentence() + seconds_of(quiet, 4.0) + self.sentence()   # 2nd: inside the window of the 1st answer
                  + seconds_of(quiet, 3.0) + self.sentence()                    # 3rd: the 2nd answer opened a new one
                  + seconds_of(quiet, d.FOLLOW_UP_S + 6.0))
        self.build(script, hook=self.playing())
        self.run_conv()
        self.assertEqual(self.started, ["Primeira.", "Segunda.", "Terceira."])
        self.assertEqual(self.conv.out_of_window, 0)

    def test_a_pause_longer_than_the_window_closes_it_again(self):
        self.heard = ["Primeira.", "Segunda."]
        script = (self.sentence() + seconds_of(quiet, d.FOLLOW_UP_S + 4.0) + self.sentence())
        self.build(script, hook=self.playing())
        self.run_conv()
        self.assertEqual(self.started, ["Primeira."])
        self.assertEqual(self.conv.out_of_window, 1)

    def test_the_exit_phrase_says_goodbye_and_ends(self):
        self.heard = ["Tchau."]
        self.build(self.sentence() + seconds_of(quiet, 0.2))
        self.run_conv()
        self.assertEqual(self.said, ["Até logo, senhor."])
        self.assertEqual(self.started, [])

    def test_standby_ignores_what_does_not_start_with_his_name(self):
        self.heard = ["Bom dia."]  # only the cheap check runs: nothing is answered, nothing is spent
        self.build(self.sentence(), standby=True)
        self.run_conv()
        self.assertEqual(self.started, [])
        self.assertEqual(self.heard, [])

    def test_standby_opens_with_his_name_and_the_same_sentence_is_the_request(self):
        self.heard = ["Jarvis, que horas são?", "Jarvis, que horas são?"]  # the check, then the full transcription
        self.build(self.sentence(), standby=True)
        self.run_conv()
        self.assertEqual(self.started, ["que horas são?"])

    def test_standby_after_the_call_the_next_sentence_needs_no_name(self):
        self.heard = ["Jarvis.", "Jarvis.", "Me fala do tempo."]
        self.build(self.sentence() + self.sentence(), standby=True)
        self.run_conv()
        self.assertEqual(self.acks, [1])
        self.assertEqual(self.started, ["Me fala do tempo."])

    def test_standby_goodbye_closes_instead_of_ending_and_the_name_opens_it_again(self):
        self.heard = ["Jarvis, tchau.", "Jarvis, tchau.", "Bom dia.", "Jarvis, que horas são?", "Jarvis, que horas são?"]
        self.build(self.sentence() + self.sentence() + self.sentence(), standby=True)
        self.run_conv()
        self.assertEqual(self.said, ["Até logo, senhor."])
        self.assertEqual(self.started, ["que horas são?"])  # the "Bom dia." in between was closed-conversation noise
        self.assertIn("  (conversa fechada: chame 'Jarvis' pra abrir)", self.logs)

    def test_standby_silence_closes_the_conversation_and_it_keeps_running(self):
        self.heard = ["Jarvis, oi.", "Jarvis, oi.", "Conversa lateral.", "Jarvis, e agora?", "Jarvis, e agora?"]
        self.build(self.sentence() + seconds_of(quiet, 6.0) + self.sentence() + self.sentence(), standby=True, idle_s=3.0,
                   hook=self.playing())
        self.run_conv()
        self.assertEqual(self.started, ["oi", "e agora?"])
        self.assertIn("  (conversa fechada: chame 'Jarvis' pra abrir)", self.logs)

    def test_an_intercepted_sentence_never_reaches_the_model(self):
        taken = []
        self.heard = ["Modo dev.", "Bom dia."]
        self.build(self.sentence() + self.sentence(), intercept=lambda text: taken.append(text) or text == "Modo dev.")
        self.run_conv()
        self.assertEqual(taken, ["Modo dev.", "Bom dia."])
        self.assertEqual(self.started, ["Bom dia."])

    def test_idle_for_too_long_ends_the_conversation(self):
        ticks = iter(range(100))
        conv = d.Conversation(lambda: None, FakeVad(), d.SpeechGate(), d.Player(open_stream=lambda r, c, dv: FakeStream()),
                              lambda a: "", lambda *a: None, clock=lambda: float(next(ticks)), idle_s=5, log=lambda m: None)
        conv.run()  # would loop forever if the idle timeout did not end it


if __name__ == "__main__":
    unittest.main()
