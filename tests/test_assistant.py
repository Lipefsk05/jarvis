import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from jarvis.assistant import BLOCKED_MESSAGE, FAILED_MESSAGE, Assistant
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
            self.assertTrue(r.humor_offered)
            self.assertAlmostEqual(budget.spent_today(), 1.0)
            system, messages = talker.calls[0]
            self.assertIn("humor=SIM", system)
            self.assertEqual(messages, [{"role": "user", "content": "oi"}])

    def test_second_turn_sends_history_and_blocks_humor(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker()
            a, _ = self.make(tmp, talker)
            a.respond(1, "oi")
            r = a.respond(1, "e aí")
            self.assertFalse(r.humor_offered)
            system, messages = talker.calls[1]
            self.assertIn("humor=NÃO", system)
            self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user"])

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
