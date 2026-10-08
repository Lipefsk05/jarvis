import random
import unittest

from jarvis.style import GREETING_HINTS, THANKS_HINTS, StyleHints, is_greeting, is_thanks


class ClassificationTest(unittest.TestCase):
    def test_greetings_including_slang_and_typos(self):
        for text in ("bom dia", "Bom diua", "boa noite", "ola", "Olá!", "opa", "Opa belezxa?", "oi, tudo bem?",
                     "e aí", "salve", "fala Jarvis", "boa tarde, senhor"):
            self.assertTrue(is_greeting(text), text)

    def test_not_greetings(self):
        for text in ("oi, preciso de ajuda com o deploy de ontem", "me explica o que é um webhook", "quais tarefas eu tenho?",
                     "tô cansado hoje", "", "!!!"):
            self.assertFalse(is_greeting(text), text)

    def test_thanks(self):
        for text in ("valeu", "vlw!", "brigadão", "Obrigado", "obrigada pela ajuda"):
            self.assertTrue(is_thanks(text), text)
        for text in ("oi", "valeu mas ainda não funciona porque o deploy falhou de novo"):
            self.assertFalse(is_thanks(text), text)


class StyleHintsTest(unittest.TestCase):
    def test_never_repeats_the_previous_hint_in_a_chat(self):
        hints = StyleHints(random.Random(1))
        previous = None
        for _ in range(60):
            current = hints.hint_for(1, "bom dia")
            self.assertNotEqual(current, previous)
            previous = current

    def test_uses_the_whole_pool_over_time(self):
        hints = StyleHints(random.Random(2))
        seen = {hints.hint_for(1, "oi").split(" Regra rígida")[0] for _ in range(80)}
        self.assertEqual(seen, set(GREETING_HINTS))

    def test_thanks_pool_and_neutral_messages(self):
        hints = StyleHints(random.Random(3))
        self.assertIn(hints.hint_for(1, "valeu").split(" Regra rígida")[0], THANKS_HINTS)
        self.assertEqual(hints.hint_for(1, "me explica o que é um container"), "")

    def test_chats_have_independent_memory(self):
        a, b = StyleHints(random.Random(4)), StyleHints(random.Random(4))
        first = a.hint_for(1, "oi")
        self.assertEqual(first, b.hint_for(2, "oi"))  # same seed, different chat id: same first draw

    def test_hint_bans_the_fallback_phrase(self):
        self.assertIn("ser útil", StyleHints().hint_for(1, "oi"))


if __name__ == "__main__":
    unittest.main()
