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
    @staticmethod
    def turn(gate, chat, text="oi", joke=True):
        """One turn: returns permission, and records a joke when permitted and the model made one."""
        allowed = gate.permitted(chat, text)
        if allowed and joke:
            gate.record_joke(chat)
        return allowed

    def test_first_turn_may_joke_then_cooldown(self):
        gate = HumorGate(min_gap=2)
        results = [self.turn(gate, 1) for _ in range(7)]
        self.assertEqual(results, [True, False, False, True, False, False, True])

    def test_permitted_slot_is_kept_when_the_model_does_not_joke(self):
        gate = HumorGate(min_gap=2)
        self.assertTrue(self.turn(gate, 1, joke=False))
        self.assertTrue(self.turn(gate, 1, joke=False))
        self.assertTrue(self.turn(gate, 1, joke=True))
        self.assertFalse(self.turn(gate, 1))

    def test_serious_turn_never_jokes_and_cooldown_keeps_running(self):
        gate = HumorGate(min_gap=2)
        self.assertTrue(self.turn(gate, 1))
        self.assertFalse(self.turn(gate, 1, "deu erro"))
        self.assertFalse(self.turn(gate, 1, "ok"))
        self.assertTrue(self.turn(gate, 1, "e agora?"))

    def test_serious_turn_does_not_consume_a_ready_slot(self):
        gate = HumorGate(min_gap=0)
        self.assertFalse(self.turn(gate, 1, "urgente!"))
        self.assertTrue(self.turn(gate, 1, "tudo bem?"))

    def test_not_funny_feedback_lengthens_gap_once(self):
        gate = HumorGate(min_gap=1, penalty_gap=3)
        self.assertTrue(self.turn(gate, 1))
        gate.feedback_not_funny(1)
        # penalty: three silent turns before the next permitted one
        self.assertEqual([self.turn(gate, 1) for _ in range(4)], [False, False, False, True])
        # that joke restores the normal gap
        self.assertEqual([self.turn(gate, 1) for _ in range(2)], [False, True])

    def test_chats_are_independent(self):
        gate = HumorGate(min_gap=5)
        self.assertTrue(self.turn(gate, 1))
        self.assertTrue(self.turn(gate, 2))


if __name__ == "__main__":
    unittest.main()
