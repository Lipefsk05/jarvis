import importlib.util
import unittest
from dataclasses import replace
from pathlib import Path

from jarvis.config import Settings
from jarvis.talker.base import Reply, TalkerError
from jarvis.talker.chain import ChainMember, ChainTalker


class Fake:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = 0

    def reply(self, system, messages, tools=None):
        self.tools = tools
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


MSGS = [{"role": "user", "content": "oi"}]


class ChainTest(unittest.TestCase):
    def test_first_member_answers_and_is_priced_with_its_own_rates(self):
        a, b = Fake(Reply("ola", 1_000_000, 0)), Fake(Reply("reserva", 1, 1))
        chain = ChainTalker([ChainMember("groq", a, 0.0, 0.0), ChainMember("anthropic", b, 1.0, 5.0)])
        r = chain.reply("sys", MSGS)
        self.assertEqual((r.text, r.provider, r.cost_usd), ("ola", "groq", 0.0))
        self.assertEqual(b.calls, 0)

    def test_falls_back_and_prices_the_provider_that_answered(self):
        a = Fake(TalkerError("RateLimitError:429"))
        b = Fake(Reply("reserva", 2_000_000, 100_000))
        chain = ChainTalker([ChainMember("groq", a, 0.0, 0.0), ChainMember("anthropic", b, 1.0, 5.0)])
        r = chain.reply("sys", MSGS)
        self.assertEqual((r.text, r.provider), ("reserva", "anthropic"))
        self.assertAlmostEqual(r.cost_usd, 2.5)  # 2*1 + 0.1*5

    def test_a_bad_key_in_one_provider_does_not_stop_the_chain(self):
        a = Fake(TalkerError("AuthenticationError:401"))
        b = Fake(Reply("ok", 1, 1))
        chain = ChainTalker([ChainMember("groq", a, 0, 0), ChainMember("gemini", b, 0, 0)])
        self.assertEqual(chain.reply("sys", MSGS).provider, "gemini")

    def test_all_failing_reports_every_provider(self):
        chain = ChainTalker([
            ChainMember("groq", Fake(TalkerError("RateLimitError:429")), 0, 0),
            ChainMember("gemini", Fake(TalkerError("ServerError:503")), 0, 0),
        ])
        with self.assertRaises(TalkerError) as ctx:
            chain.reply("sys", MSGS)
        message = str(ctx.exception)
        self.assertIn("groq:RateLimitError:429", message)
        self.assertIn("gemini:ServerError:503", message)

    def test_tools_are_passed_to_every_member_tried(self):
        a, b = Fake(TalkerError("RateLimitError:429")), Fake(Reply("ok", 1, 1))
        chain = ChainTalker([ChainMember("groq", a, 0, 0), ChainMember("gemini", b, 0, 0)])
        chain.reply("sys", MSGS, [{"type": "function"}])
        self.assertEqual((a.tools, b.tools), ([{"type": "function"}], [{"type": "function"}]))

    def test_names(self):
        chain = ChainTalker([ChainMember("a", Fake(None), 0, 0), ChainMember("b", Fake(None), 0, 0)])
        self.assertEqual(chain.names, ["a", "b"])


HAS_SDKS = all(importlib.util.find_spec(m) for m in ("groq", "google.genai", "anthropic"))


@unittest.skipUnless(HAS_SDKS, "provider SDKs not installed")
class FactoryTest(unittest.TestCase):
    def settings(self, **env):
        return Settings.load(env_path=Path("/nonexistent/.env"), environ=env)

    def test_primary_then_fallback_with_own_prices(self):
        from jarvis.talker.factory import build_talker

        s = self.settings(
            JARVIS_TALKER_PROVIDER="groq", GROQ_API_KEY="g", GEMINI_API_KEY="x",
            JARVIS_TALKER_FALLBACK_PROVIDERS="gemini",
        )
        chain = build_talker(s)
        self.assertEqual(chain.names, ["groq", "gemini"])

    def test_fallback_without_key_is_skipped(self):
        from jarvis.talker.factory import build_talker

        s = self.settings(
            JARVIS_TALKER_PROVIDER="groq", GROQ_API_KEY="g",
            JARVIS_TALKER_FALLBACK_PROVIDERS="gemini,anthropic",
        )
        self.assertEqual(build_talker(s).names, ["groq"])

    def test_anthropic_fallback_is_priced(self):
        from jarvis.talker.factory import build_talker

        s = self.settings(
            JARVIS_TALKER_PROVIDER="groq", GROQ_API_KEY="g", ANTHROPIC_API_KEY="a",
            JARVIS_TALKER_FALLBACK_PROVIDERS="anthropic",
        )
        chain = build_talker(s)
        self.assertEqual(chain.names, ["groq", "anthropic"])
        self.assertEqual((chain._members[1].price_in, chain._members[1].price_out), (1.0, 5.0))
        self.assertEqual((chain._members[0].price_in, chain._members[0].price_out), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
