import unittest
from datetime import datetime

from jarvis.commands import parse_note_request
from jarvis.tone import period_greeting, polish, strip_markdown

AFTERNOON = datetime(2026, 10, 9, 17, 0)


def clean(user, reply, now=AFTERNOON, greeting=False, request=False, help_ok=False):
    return polish(user, reply, now, is_greeting=greeting, greeting_request=request, allows_help=help_ok)


class MarkdownTest(unittest.TestCase):
    def test_bold_code_headings_and_bullets_go_but_numbering_stays(self):
        raw = "## Cache\n1. **Objetivo** – rápido\n- usa `LRU`\n* __nível__ L1"
        self.assertEqual(strip_markdown(raw), "Cache\n1. Objetivo – rápido\nusa LRU\nnível L1")


class OpenerTest(unittest.TestCase):
    def test_reflex_opener_is_dropped(self):
        self.assertEqual(clean("acho que vou dormir cedo", "Entendo, senhor. Dormir cedo costuma ser a melhor escolha."),
                         "Dormir cedo costuma ser a melhor escolha.")

    def test_greeting_is_dropped_when_nobody_greeted(self):
        self.assertEqual(clean("qual a capital do Peru?", "Bom dia, senhor. Lima."), "Lima.")

    def test_a_reply_that_is_only_a_greeting_is_kept(self):
        self.assertEqual(clean("kkk boa", "Boa noite, senhor."), "Boa noite, senhor.")


class GreetingTest(unittest.TestCase):
    def test_slang_greeting_gets_the_part_of_the_day_from_the_clock(self):
        self.assertEqual(clean("e aí", "Bom dia, senhor. Estou à disposição.", greeting=True, help_ok=True),
                         "Boa tarde, senhor. Estou à disposição.")

    def test_users_own_period_greeting_is_answered_in_kind(self):
        self.assertEqual(clean("bom dia", "Bom dia, senhor.", greeting=True), "Bom dia, senhor.")

    def test_greeting_plus_request_keeps_the_greeting(self):
        self.assertEqual(clean("oi, preciso de um resumo", "Bom dia, senhor. Segue o resumo.", request=True),
                         "Boa tarde, senhor. Segue o resumo.")

    def test_the_period_follows_the_clock(self):
        self.assertEqual([period_greeting(datetime(2026, 1, 1, h)) for h in (4, 5, 11, 12, 17, 18, 23)],
                         ["Boa noite", "Bom dia", "Bom dia", "Boa tarde", "Boa tarde", "Boa noite", "Boa noite"])


class OfferTest(unittest.TestCase):
    def test_closing_offer_after_a_real_answer_is_dropped(self):
        self.assertEqual(clean("o que é DNS?", "Traduz nomes em endereços. Posso ajudar em mais alguma coisa?"),
                         "Traduz nomes em endereços.")

    def test_greeting_without_help_hint_loses_the_stock_offer_but_keeps_the_greeting(self):
        self.assertEqual(clean("oi", "Boa tarde, senhor. Em que posso ser útil?", greeting=True), "Boa tarde, senhor.")

    def test_greeting_with_help_hint_keeps_the_offer(self):
        self.assertEqual(clean("oi", "Boa tarde, senhor. Em que posso ser útil?", greeting=True, help_ok=True),
                         "Boa tarde, senhor. Em que posso ser útil?")

    def test_a_lone_offer_sentence_is_never_emptied(self):
        self.assertEqual(clean("hm", "Em que posso ajudar?"), "Em que posso ajudar?")


class NotePhraseTest(unittest.TestCase):
    def test_nao_esquece_que_is_a_note_request(self):
        self.assertEqual(parse_note_request("não esquece que o carro está na oficina"), "o carro está na oficina")
        self.assertEqual(parse_note_request("Nao esqueca que a reunião mudou"), "a reunião mudou")

    def test_other_uses_of_esquecer_are_left_to_the_model(self):
        for text in ("eu sempre esqueço as chaves", "não me deixa esquecer de pagar a luz", "não esquece"):
            self.assertIsNone(parse_note_request(text), text)


if __name__ == "__main__":
    unittest.main()
