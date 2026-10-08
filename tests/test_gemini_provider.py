import importlib.util
import unittest
from types import SimpleNamespace

from jarvis.talker.base import TalkerError

HAS_SDK = importlib.util.find_spec("google.genai") is not None


class FakeApiError(Exception):
    def __init__(self, code):
        super().__init__(f"fake {code}")
        self.code = code


def response(text, prompt=10, out=5, thoughts=0):
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt, candidates_token_count=out, thoughts_token_count=thoughts
        ),
    )


@unittest.skipUnless(HAS_SDK, "google-genai not installed")
class GeminiFallbackTest(unittest.TestCase):
    def make(self, outcomes):
        from google.genai import types

        from jarvis.talker.gemini_provider import GeminiTalker

        talker = GeminiTalker.__new__(GeminiTalker)
        talker._types = types
        talker._models = list(outcomes)
        talker._max_tokens = 400
        talker.tried = []

        def fake_generate(model, system, contents):
            talker.tried.append(model)
            outcome = outcomes[model]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        talker._generate = fake_generate
        return talker

    MSGS = [{"role": "user", "content": "oi"}]

    def test_falls_back_on_overload(self):
        t = self.make({"a": FakeApiError(503), "b": response("Boa tarde, senhor.", 100, 20, 7)})
        reply = t.reply("sys", self.MSGS)
        self.assertEqual(t.tried, ["a", "b"])
        self.assertEqual((reply.text, reply.input_tokens, reply.output_tokens), ("Boa tarde, senhor.", 100, 27))

    def test_does_not_fall_back_on_auth_error(self):
        t = self.make({"a": FakeApiError(401), "b": response("x")})
        with self.assertRaises(TalkerError) as ctx:
            t.reply("sys", self.MSGS)
        self.assertEqual(t.tried, ["a"])
        self.assertIn("401", str(ctx.exception))

    def test_empty_response_tries_next_model(self):
        t = self.make({"a": response("   "), "b": response("ok")})
        self.assertEqual(t.reply("sys", self.MSGS).text, "ok")

    def test_all_models_failing_reports_last_error(self):
        t = self.make({"a": FakeApiError(503), "b": FakeApiError(504)})
        with self.assertRaises(TalkerError) as ctx:
            t.reply("sys", self.MSGS)
        self.assertIn("504", str(ctx.exception))

    def test_thinking_disabled_only_for_2_5_models(self):
        t = self.make({})
        self.assertIsNotNone(t._config("gemini-2.5-flash", "s").thinking_config)
        self.assertIsNone(t._config("gemini-3.5-flash", "s").thinking_config)


if __name__ == "__main__":
    unittest.main()
