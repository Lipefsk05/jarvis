import unittest
from types import SimpleNamespace

from jarvis.audio import MAX_BYTES, GroqTranscriber, TranscribeError, check_audio, transcript_line


class FakeError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code


class FakeClient:
    def __init__(self, text="olá mundo", error=None):
        self.calls = []
        self._text, self._error = text, error
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return SimpleNamespace(text=self._text)


class CheckAudioTest(unittest.TestCase):
    def test_fine_audio_passes(self):
        self.assertIsNone(check_audio(30, 100_000))
        self.assertIsNone(check_audio(None, None))

    def test_too_long_or_too_big_is_refused_with_a_sentence(self):
        self.assertIn("minutos", check_audio(301, 1000))
        self.assertIn("grande demais", check_audio(10, MAX_BYTES + 1))


class TranscriberTest(unittest.TestCase):
    def test_sends_portuguese_audio_and_strips_the_text(self):
        client = FakeClient("  anota que preciso de pão  ")
        text = GroqTranscriber("k", client=client).transcribe("voz.ogg", b"abc")
        self.assertEqual(text, "anota que preciso de pão")
        call = client.calls[0]
        self.assertEqual((call["file"], call["language"], call["model"]), (("voz.ogg", b"abc"), "pt", "whisper-large-v3-turbo"))

    def test_empty_transcript_is_an_error_with_a_reason(self):
        with self.assertRaises(TranscribeError) as ctx:
            GroqTranscriber("k", client=FakeClient("   ")).transcribe("voz.ogg", b"x")
        self.assertIn("Não entendi", ctx.exception.reason)

    def test_quota_error_says_so_and_other_errors_stay_generic(self):
        with self.assertRaises(TranscribeError) as quota:
            GroqTranscriber("k", client=FakeClient(error=FakeError(429))).transcribe("a.ogg", b"x")
        self.assertIn("limite", quota.exception.reason)
        with self.assertRaises(TranscribeError) as other:
            GroqTranscriber("k", client=FakeClient(error=FakeError(500))).transcribe("a.ogg", b"x")
        self.assertIn("Não consegui transcrever", other.exception.reason)


class TranscriptLineTest(unittest.TestCase):
    def test_shows_the_text_and_cuts_a_long_one(self):
        self.assertEqual(transcript_line("oi"), "🎙 “oi”")
        self.assertLess(len(transcript_line("x" * 5000)), 700)


if __name__ == "__main__":
    unittest.main()
