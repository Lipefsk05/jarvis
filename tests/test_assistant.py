import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from jarvis.assistant import BLOCKED_MESSAGE, FAILED_MESSAGE, Assistant, split_joke
from jarvis.budget import Budget
from jarvis.conversation import History
from jarvis.humor import HumorGate
from jarvis.talker.base import Reply, TalkerError

NOW = datetime(2026, 10, 8, 14, 30)
TEMPLATE = "SYS humor={{humor_permitido}} estado={{estado_atual}}"


class FakeTalker:
    def __init__(self, replies=None, error=None):
        self.calls = []
        self._replies = list(replies or [Reply("ok", 1000, 100)])
        self._error = error

    def reply(self, system, messages):
        self.calls.append((system, messages))
        if self._error:
            raise self._error
        return self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]


class AssistantTest(unittest.TestCase):
    def make(self, tmp, talker, cap=10.0, estado=None):
        budget = Budget(Path(tmp) / "usage.json", cap, 1.0, 5.0, clock=lambda: NOW)
        return Assistant(
            talker=talker, budget=budget, gate=HumorGate(min_gap=2), history=History(),
            template=TEMPLATE, clock=lambda: NOW, estado_path=estado,
        ), budget

    def test_happy_path_records_history_and_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker([Reply("Boa tarde, senhor.", 1_000_000, 0)])
            a, budget = self.make(tmp, talker)
            r = a.respond(1, "oi")
            self.assertEqual(r.text, "Boa tarde, senhor.")
            self.assertFalse(r.humor_offered)  # no joke mark -> no button
            self.assertAlmostEqual(budget.spent_today(), 1.0)
            system, messages = talker.calls[0]
            self.assertIn("humor=SIM", system)
            self.assertEqual(messages, [{"role": "user", "content": "oi"}])

    def test_provider_and_explicit_cost_come_from_the_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker([Reply("oi, senhor", 5_000_000, 0, provider="groq", cost_usd=0.0)])
            a, budget = self.make(tmp, talker)
            r = a.respond(1, "oi")
            self.assertEqual(r.provider, "groq")
            self.assertEqual(budget.spent_today(), 0.0)  # default price would have said US$ 5

    def test_joke_tag_is_unwrapped_and_flags_the_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker([Reply("Bom dia, senhor. [[humor: Pontualidade rara, para variar.]]", 10, 5)])
            a, _ = self.make(tmp, talker)
            r = a.respond(1, "oi")
            self.assertEqual(r.text, "Bom dia, senhor. Pontualidade rara, para variar.")
            self.assertTrue(r.humor_offered)
            a.respond(1, "e aí")
            history = talker.calls[1][1]
            self.assertEqual(history[1], {"role": "assistant", "content": "Bom dia, senhor. Pontualidade rara, para variar."})

    def test_bare_humor_tag_is_not_a_joke(self):
        # Seen live with gpt-oss-120b: "[[humor]]" appended to plain greetings and explanations.
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker([Reply("Bom dia, senhor. [[humor]]", 10, 5), Reply("ok", 10, 5)])
            a, _ = self.make(tmp, talker)
            r = a.respond(1, "oi")
            self.assertEqual(r.text, "Bom dia, senhor.")
            self.assertFalse(r.humor_offered)
            a.respond(1, "e aí")
            self.assertIn("humor=SIM", talker.calls[1][0])  # the slot was not consumed

    def test_split_joke_cases(self):
        cases = [
            ("Boa, senhor. [humor: sempre pontual, esse senhor]", "Boa, senhor. sempre pontual, esse senhor", True),
            ("Boa, senhor. [[Humor]]", "Boa, senhor.", False),
            ("Qual foi o erro, senhor?]]", "Qual foi o erro, senhor?", False),
            ("Veja a nota [1] acima.", "Veja a nota [1] acima.", False),
            ("Veja [[humor: sim]] isso.", "Veja isso.", False),
            ("A [[humor: piada com várias palavras]] fica no meio.", "A piada com várias palavras fica no meio.", True),
        ]
        for raw, expected, joked in cases:
            self.assertEqual(split_joke(raw), (expected, joked), raw)

    def test_cooldown_starts_only_after_a_real_joke(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker([Reply("sem graça", 10, 5),
                                 Reply("ok [[humor: uma observação seca e espirituosa]]", 10, 5), Reply("x", 10, 5)])
            a, _ = self.make(tmp, talker)
            a.respond(1, "oi")        # permitted, no joke made -> slot kept
            a.respond(1, "e aí")      # permitted again, joke made
            a.respond(1, "certo")     # now in cooldown
            self.assertIn("humor=SIM", talker.calls[0][0])
            self.assertIn("humor=SIM", talker.calls[1][0])
            self.assertIn("humor=NÃO", talker.calls[2][0])

    def test_reply_that_is_only_the_mark_counts_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker([Reply("[[humor]]", 10, 5)])
            a, _ = self.make(tmp, talker)
            self.assertEqual(a.respond(1, "oi").text, FAILED_MESSAGE)
            self.assertEqual(a._history.messages(1), [])

    def test_blocked_when_over_budget_without_calling_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker()
            a, budget = self.make(tmp, talker, cap=0.001)
            budget.add(1_000_000, 0)
            r = a.respond(1, "oi")
            self.assertTrue(r.blocked)
            self.assertEqual(r.text, BLOCKED_MESSAGE)
            self.assertEqual(talker.calls, [])

    def test_provider_failure_rolls_back_history_and_hides_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker(error=TalkerError("RateLimitError"))
            a, budget = self.make(tmp, talker)
            r = a.respond(1, "oi")
            self.assertEqual(r.text, FAILED_MESSAGE)
            self.assertEqual(budget.spent_today(), 0.0)
            a._talker = FakeTalker()
            a.respond(1, "de novo")
            self.assertEqual(a._talker.calls[0][1], [{"role": "user", "content": "de novo"}])

    def test_warns_when_crossing_eighty_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker([Reply("x", 900_000, 0)])
            a, _ = self.make(tmp, talker, cap=1.0)
            self.assertTrue(a.respond(1, "oi").warn_budget)
            self.assertFalse(a.respond(1, "oi").warn_budget)

    def test_estado_atual_is_injected(self):
        with tempfile.TemporaryDirectory() as tmp:
            estado = Path(tmp) / "estado.md"
            estado.write_text("projeto Jarvis em andamento", encoding="utf-8")
            talker = FakeTalker()
            a, _ = self.make(tmp, talker, estado=estado)
            a.respond(1, "oi")
            self.assertIn("projeto Jarvis em andamento", talker.calls[0][0])


if __name__ == "__main__":
    unittest.main()
