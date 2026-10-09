import importlib.util
import unittest
from types import SimpleNamespace

from jarvis.actions import TOOLS
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

        def fake_generate(model, system, contents, tools=None):
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

    def test_thinking_is_minimised_per_model_family(self):
        from google.genai import types

        t = self.make({})
        self.assertEqual(t._config("gemini-2.5-flash", "s").thinking_config.thinking_budget, 0)
        self.assertEqual(
            t._config("gemini-3.5-flash", "s").thinking_config.thinking_level,
            types.ThinkingLevel.MINIMAL,
        )
        self.assertIsNone(t._config("gemini-flash-latest", "s").thinking_config)

    def test_truncated_reply_is_discarded_and_next_model_tried(self):
        cut = response("Gostaria de ser o portador de boas notícias,")
        cut.candidates = [SimpleNamespace(finish_reason="FinishReason.MAX_TOKENS")]
        t = self.make({"a": cut, "b": response("Ainda não consigo, senhor.")})
        self.assertEqual(t.reply("sys", self.MSGS).text, "Ainda não consigo, senhor.")
        self.assertEqual(t.tried, ["a", "b"])

    def test_tool_call_becomes_a_reply_without_text(self):
        call = SimpleNamespace(name="anotar", args={"texto": "comprar pão"})
        called = response("")
        called.function_calls = [call]
        t = self.make({"a": called})
        reply = t.reply("sys", self.MSGS, tools=TOOLS)
        self.assertEqual((reply.text, reply.tool_call.name, reply.tool_call.arguments), ("", "anotar", {"texto": "comprar pão"}))

    def test_every_real_tool_converts_to_a_declaration_and_the_sdk_runs_none_itself(self):
        t = self.make({})
        config = t._config("gemini-2.5-flash", "s", TOOLS)
        declared = [d.name for d in config.tools[0].function_declarations]
        self.assertEqual(declared, [x["function"]["name"] for x in TOOLS])
        self.assertTrue(config.automatic_function_calling.disable)
        by_name = {d.name: d for d in config.tools[0].function_declarations}
        self.assertIsNone(by_name["ver_gasto"].parameters_json_schema)  # no arguments, no schema
        self.assertEqual(by_name["criar_lembrete"].parameters_json_schema["properties"]["antecedencia_minutos"]["type"], ["integer", "null"])

    def test_no_tools_means_none_in_the_config(self):
        self.assertIsNone(self.make({})._config("gemini-2.5-flash", "s").tools)


if __name__ == "__main__":
    unittest.main()
