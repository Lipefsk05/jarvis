import random
import unittest

from jarvis.style import (
    AVOID_RULE, GREETING_AND_REQUEST, GREETING_POOL, HELP_HINTS, NOT_A_GREETING, STIFF_RULE, THANKS_HINTS,
    StyleHints, is_greeting, is_thanks, starts_with_greeting,
)


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


class PraiseIsNotAGreetingTest(unittest.TestCase):
    def test_praise_and_questions_get_the_not_a_greeting_hint(self):
        # The live bug: "Kkkkkk boa, mas eai oq vc pode fazer?" was answered with "Boa noite, senhor."
        hints = StyleHints(random.Random(6))
        for text in ("Kkkkkk boa, mas eai oq vc pode fazer?", "boa", "boa!", "show", "top demais", "kkkk boa essa"):
            self.assertFalse(is_greeting(text), text)
            self.assertEqual(hints.hint_for(1, text), NOT_A_GREETING, text)

    def test_greeting_followed_by_a_request(self):
        self.assertTrue(starts_with_greeting("oi, preciso de ajuda com o deploy de ontem"))
        self.assertTrue(starts_with_greeting("boa tarde, quais tarefas eu tenho hoje?"))
        self.assertFalse(starts_with_greeting("kkkk boa, mas eai o que você pode fazer?"))
        self.assertFalse(starts_with_greeting("oi"))  # a bare greeting is handled by is_greeting
        self.assertEqual(StyleHints().hint_for(1, "oi, preciso de ajuda com o deploy de ontem"), GREETING_AND_REQUEST)


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
        seen = {hints.hint_for(1, "oi").split(f" {STIFF_RULE}")[0] for _ in range(120)}
        self.assertEqual(seen, set(GREETING_POOL))

    def test_thanks_pool_and_neutral_messages(self):
        hints = StyleHints(random.Random(3))
        self.assertIn(hints.hint_for(1, "valeu").split(f" {STIFF_RULE}")[0], THANKS_HINTS)
        self.assertEqual(hints.hint_for(1, "me explica o que é um container"), NOT_A_GREETING)

    def test_chats_have_independent_memory(self):
        a, b = StyleHints(random.Random(4)), StyleHints(random.Random(4))
        first = a.hint_for(1, "oi")
        self.assertEqual(first, b.hint_for(2, "oi"))  # same seed, different chat id: same first draw

    def test_help_offer_is_allowed_only_by_the_help_hints(self):
        hints = StyleHints(random.Random(5))
        with_help = without_help = 0
        for _ in range(300):
            hint = hints.hint_for(1, "oi")
            self.assertIn(STIFF_RULE, hint)  # never stiff, whatever the hint
            if AVOID_RULE in hint:
                without_help += 1
            else:
                self.assertTrue(any(hint.startswith(h) for h in HELP_HINTS))
                with_help += 1
        self.assertGreater(with_help, 0)
        self.assertGreater(without_help, with_help)  # an occasional offer, not the default

    def test_no_hint_asks_for_stiff_wording(self):
        for text in GREETING_POOL + THANKS_HINTS:
            self.assertNotIn("ocupar", text)


if __name__ == "__main__":
    unittest.main()
