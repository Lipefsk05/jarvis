import importlib.util
import unittest
from types import SimpleNamespace

from jarvis.talker.base import TalkerError

HAS_SDK = importlib.util.find_spec("groq") is not None


class FakeApiError(Exception):
    def __init__(self, status_code):
        super().__init__(f"fake {status_code}")
        self.status_code = status_code


def completion(text, finish="stop", prompt=10, out=5):
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=out),
    )


@unittest.skipUnless(HAS_SDK, "groq not installed")
class GroqFallbackTest(unittest.TestCase):
    MSGS = [{"role": "user", "content": "oi"}]

    def make(self, outcomes):
        from jarvis.talker.groq_provider import GroqTalker

        talker = GroqTalker.__new__(GroqTalker)
        talker._models = list(outcomes)
        talker._max_tokens = 400
        talker.tried = []
        talker.system_seen = None

        def fake_complete(model, system, messages):
            talker.tried.append(model)
            outcome = outcomes[model]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        talker._complete = fake_complete
        return talker

    def test_success_reports_tokens(self):
        t = self.make({"a": completion("Boa tarde, senhor.", prompt=120, out=18)})
        r = t.reply("sys", self.MSGS)
        self.assertEqual((r.text, r.input_tokens, r.output_tokens), ("Boa tarde, senhor.", 120, 18))

    def test_falls_back_on_rate_limit(self):
        t = self.make({"a": FakeApiError(429), "b": completion("ok")})
        self.assertEqual(t.reply("sys", self.MSGS).text, "ok")
        self.assertEqual(t.tried, ["a", "b"])

    def test_no_fallback_on_auth_error(self):
        t = self.make({"a": FakeApiError(401), "b": completion("ok")})
        with self.assertRaises(TalkerError) as ctx:
            t.reply("sys", self.MSGS)
        self.assertEqual(t.tried, ["a"])
        self.assertIn("401", str(ctx.exception))

    def test_truncated_reply_is_discarded(self):
        t = self.make({"a": completion("Gostaria de ser", finish="length"), "b": completion("Inteiro.")})
        self.assertEqual(t.reply("sys", self.MSGS).text, "Inteiro.")

    def test_empty_choices_tries_next(self):
        t = self.make({"a": SimpleNamespace(choices=[], usage=None), "b": completion("ok")})
        self.assertEqual(t.reply("sys", self.MSGS).text, "ok")


if __name__ == "__main__":
    unittest.main()
