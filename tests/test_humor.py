import unittest

from jarvis.humor import HumorGate, is_serious


class IsSeriousTest(unittest.TestCase):
    def test_serious_keywords_with_and_without_accents(self):
        for text in ("deu um erro feio", "É URGÊNCIA total", "preciso pagar a fatura",
                     "vou apagar a pasta", "tô com pressa", "ele morreu ontem"):
            self.assertTrue(is_serious(text), text)

    def test_all_caps_is_serious(self):
        self.assertTrue(is_serious("PARA DE FAZER ISSO AGORA"))

    def test_casual_is_not_serious(self):
        for text in ("bom dia", "me conta uma curiosidade", "ok", "VLW"):
            self.assertFalse(is_serious(text), text)


class HumorGateTest(unittest.TestCase):
    def test_first_turn_may_joke_then_cooldown(self):
        gate = HumorGate(min_gap=2)
        results = [gate.decide(1, "oi") for _ in range(7)]
        # offers on turns 1, 4, 7 (two replies in between)
        self.assertEqual(results, [True, False, False, True, False, False, True])

    def test_serious_turn_never_jokes_and_keeps_cooldown_running(self):
        gate = HumorGate(min_gap=2)
        self.assertTrue(gate.decide(1, "oi"))
        self.assertFalse(gate.decide(1, "deu erro"))
        self.assertFalse(gate.decide(1, "ok"))
        self.assertTrue(gate.decide(1, "e agora?"))

    def test_serious_turn_does_not_consume_a_ready_slot(self):
        gate = HumorGate(min_gap=0)
        self.assertFalse(gate.decide(1, "urgente!"))
        self.assertTrue(gate.decide(1, "tudo bem?"))

    def test_not_funny_feedback_lengthens_gap_once(self):
        gate = HumorGate(min_gap=1, penalty_gap=3)
        self.assertTrue(gate.decide(1, "oi"))
        gate.feedback_not_funny(1)
        # penalty: three silent turns before the next offer
        self.assertEqual([gate.decide(1, "x") for _ in range(4)], [False, False, False, True])
        # afterwards back to the normal gap
        self.assertEqual([gate.decide(1, "x") for _ in range(2)], [False, True])

    def test_chats_are_independent(self):
        gate = HumorGate(min_gap=5)
        self.assertTrue(gate.decide(1, "oi"))
        self.assertTrue(gate.decide(2, "oi"))


if __name__ == "__main__":
    unittest.main()
