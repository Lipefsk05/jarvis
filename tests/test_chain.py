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

    def reply(self, system, messages, tools=None, private=False):
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

    def test_info_describes_each_member_for_the_usage_screen(self):
        class Talk:
            _models = ["main-model", "other"]
            limits = {"requests_remaining": 5}

        chain = ChainTalker([ChainMember("groq", Talk(), 0.0, 0.0), ChainMember("anthropic", Fake(None), 1.0, 5.0)])
        first, second = chain.info()
        self.assertEqual((first["name"], first["model"], first["free"], first["limits"]), ("groq", "main-model", True, {"requests_remaining": 5}))
        self.assertEqual((second["free"], second["limits"], second["model"]), (False, None, ""))

    def test_names(self):
        chain = ChainTalker([ChainMember("a", Fake(None), 0, 0), ChainMember("b", Fake(None), 0, 0)])
        self.assertEqual(chain.names, ["a", "b"])


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class CircuitBreakerTest(unittest.TestCase):
    def chain(self, first_error, clock=None):
        a, b = Fake(first_error), Fake(Reply("reserva", 1, 1))
        clock = clock or Clock()
        return ChainTalker([ChainMember("groq", a, 0, 0), ChainMember("gemini", b, 0, 0)], clock=clock), a, b, clock

    def test_failed_provider_is_skipped_on_the_next_messages(self):
        chain, a, b, _ = self.chain(TalkerError("APITimeoutError:None"))
        chain.reply("s", MSGS)
        chain.reply("s", MSGS)
        chain.reply("s", MSGS)
        self.assertEqual((a.calls, b.calls), (1, 3))

    def test_provider_is_tried_again_after_the_cooldown(self):
        chain, a, b, clock = self.chain(TalkerError("RateLimitError", 429))
        chain.reply("s", MSGS)
        clock.now += 59
        chain.reply("s", MSGS)
        self.assertEqual(a.calls, 1)
        clock.now += 2
        chain.reply("s", MSGS)
        self.assertEqual(a.calls, 2)

    def test_rate_limit_rests_shorter_than_a_bad_key(self):
        rate, _, _, clock = self.chain(TalkerError("RateLimitError", 429))
        key, key_a, _, key_clock = self.chain(TalkerError("AuthenticationError", 401))
        rate.reply("s", MSGS)
        key.reply("s", MSGS)
        clock.now += 120
        key_clock.now += 120
        rate.reply("s", MSGS)
        key.reply("s", MSGS)
        self.assertEqual(rate._members[0].talker.calls, 2)
        self.assertEqual(key_a.calls, 1)

    def test_a_cut_or_empty_answer_does_not_bench_the_provider(self):
        for message in ("MaxTokens", "EmptyResponse"):
            chain, a, b, _ = self.chain(TalkerError(message))
            chain.reply("s", MSGS)
            chain.reply("s", MSGS)
            self.assertEqual(a.calls, 2, message)

    def test_a_bad_request_does_not_bench_the_provider(self):
        chain, a, _, _ = self.chain(TalkerError("BadRequestError", 400))
        chain.reply("s", MSGS)
        chain.reply("s", MSGS)
        self.assertEqual(a.calls, 2)

    def test_server_errors_bench_the_provider(self):
        chain, a, _, _ = self.chain(TalkerError("InternalServerError", 503))
        chain.reply("s", MSGS)
        chain.reply("s", MSGS)
        self.assertEqual(a.calls, 1)

    def test_when_everyone_is_resting_all_are_tried_anyway(self):
        a, b = Fake(TalkerError("RateLimitError", 429)), Fake(TalkerError("RateLimitError", 429))
        chain = ChainTalker([ChainMember("groq", a, 0, 0), ChainMember("gemini", b, 0, 0)], clock=Clock())
        with self.assertRaises(TalkerError):
            chain.reply("s", MSGS)
        b.outcome = Reply("voltei", 1, 1)
        self.assertEqual(chain.reply("s", MSGS).text, "voltei")
        self.assertEqual((a.calls, b.calls), (2, 2))

    def test_success_clears_the_bench(self):
        chain, a, b, clock = self.chain(TalkerError("RateLimitError", 429))
        chain.reply("s", MSGS)
        clock.now += 61
        a.outcome = Reply("de volta", 1, 1)
        self.assertEqual(chain.reply("s", MSGS).provider, "groq")
        self.assertEqual(chain.reply("s", MSGS).provider, "groq")


class PrivateContextTest(unittest.TestCase):
    def test_private_context_never_reaches_a_provider_that_may_keep_it(self):
        a, b = Fake(TalkerError("RateLimitError", 429)), Fake(Reply("reserva", 1, 1))
        chain = ChainTalker([ChainMember("groq", a, 0, 0), ChainMember("gemini", b, 0, 0, private_ok=False)])
        with self.assertRaises(TalkerError):
            chain.reply("sys com tarefas", MSGS, private=True)
        self.assertEqual(b.calls, 0)

    def test_without_private_context_the_reserve_still_answers(self):
        a, b = Fake(TalkerError("RateLimitError", 429)), Fake(Reply("reserva", 1, 1))
        chain = ChainTalker([ChainMember("groq", a, 0, 0), ChainMember("gemini", b, 0, 0, private_ok=False)])
        self.assertEqual(chain.reply("sys", MSGS).provider, "gemini")


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
