import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from jarvis import research as r
from jarvis import websearch as ws

NOW = datetime(2026, 10, 20, 21, 0)


class ScopeTest(unittest.TestCase):
    def test_place_said_in_the_request(self):
        self.assertEqual(r.scope_in_text("pesquisa no Mind tudo sobre o Forge"), r.MIND)
        self.assertEqual(r.scope_in_text("procura nas minhas notas o que decidi"), r.MIND)
        self.assertEqual(r.scope_in_text("pesquisa na internet o preço do dólar"), r.WEB)
        self.assertEqual(r.scope_in_text("descobre por fora quanto custa"), r.WEB)

    def test_not_said_or_said_twice_means_ask(self):
        self.assertIsNone(r.scope_in_text("pesquisa o preço do dólar"))
        self.assertIsNone(r.scope_in_text("pesquisa no Mind e na internet sobre o Forge"))

    def test_answers_to_the_question(self):
        for text, expected in (("mind", r.MIND), ("no Mind", r.MIND), ("nas notas", r.MIND), ("internet", r.WEB),
                               ("na internet", r.WEB), ("por fora", r.WEB), ("google", r.WEB)):
            self.assertEqual(r.parse_scope_answer(text), expected, text)
        for text in ("oi", "pode ser", "mind e internet", "quanto custa o dólar hoje na cotação de ontem à noite"):
            self.assertIsNone(r.parse_scope_answer(text), text)

    def test_deep_or_quick(self):
        self.assertFalse(r.is_deep("pesquisa o preço do dólar hoje"))
        self.assertFalse(r.is_deep("procura quando sai o próximo Flutter"))
        for text in ("compara Firebase e Supabase", "levanta o mercado de apps de finanças", "investiga por que o Play recusou",
                     "analisa as alternativas ao Groq", "x" * 250):
            self.assertTrue(r.is_deep(text), text)


class OffersTest(unittest.TestCase):
    def test_offer_expires_and_clears(self):
        offers = r.Offers()
        offers.offer(1, "pesquisa x", NOW)
        self.assertEqual(offers.pending(1, NOW + timedelta(minutes=9)), "pesquisa x")
        self.assertIsNone(offers.pending(1, NOW + timedelta(minutes=11)))
        offers.offer(1, "y", NOW)
        offers.clear(1)
        self.assertIsNone(offers.pending(1, NOW))

    def test_last_quick_is_remembered_per_chat(self):
        offers = r.Offers()
        offers.remember_quick(1, "dólar")
        self.assertEqual(offers.last_quick(1), "dólar")
        self.assertIsNone(offers.last_quick(2))


def response(text, urls=()):
    chunks = [SimpleNamespace(web=SimpleNamespace(uri=u, title=f"Site {i}")) for i, u in enumerate(urls)]
    meta = SimpleNamespace(grounding_chunks=chunks)
    return SimpleNamespace(text=text, candidates=[SimpleNamespace(grounding_metadata=meta)])


class WebSearchTest(unittest.TestCase):
    def test_text_and_unique_sources(self):
        answer = ws.parse_response(response(" O dólar está a R$ 5,40. ", ["https://a.com", "https://a.com", "https://b.com"]))
        self.assertEqual(answer.text, "O dólar está a R$ 5,40.")
        self.assertEqual([u for _, u in answer.sources], ["https://a.com", "https://b.com"])
        text = ws.format_answer(answer)
        self.assertIn('Fontes: <a href="https://a.com">Site 0</a>', text)
        self.assertNotIn("https://a.com\n", text)  # a short name, not the raw link
        self.assertEqual(ws.format_answer(ws.Answer("a < b & c", ())), "a &lt; b &amp; c")  # never breaks the HTML

    def test_answer_without_sources_or_metadata_is_still_an_answer(self):
        self.assertEqual(ws.parse_response(SimpleNamespace(text="ok", candidates=[])).sources, ())

    def test_empty_answer_is_an_error(self):
        with self.assertRaises(ws.SearchError):
            ws.parse_response(response(" "))

    def test_missing_key_and_sdk_failures_become_search_errors(self):
        from datetime import date
        with self.assertRaises(ws.SearchError):
            ws.gemini_search("x", "", date(2026, 10, 20))

        class Boom:
            def __init__(self, **kw): pass
            @property
            def models(self): raise RuntimeError("429")
        with self.assertRaises(ws.SearchError):
            ws.gemini_search("x", "key", date(2026, 10, 20), client_factory=Boom)


if __name__ == "__main__":
    unittest.main()
