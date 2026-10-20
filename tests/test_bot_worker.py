"""A research verb in a plain message reaches the Worker end to end, with no model call; /pedidos shows it."""
import unittest

from test_bot_reminders import HAS_TELEGRAM, SimpleNamespace, _BotCase, FakeBot, FakeMessage, asyncio


@unittest.skipUnless(HAS_TELEGRAM, "python-telegram-bot not installed")
class BotWorkerTest(_BotCase):
    def setUp(self):
        super().setUp()
        self.callbacks = {h.callback.__name__: h.callback for group in self.app.handlers.values() for h in group
                          if hasattr(h, "callback")}

    def send(self, handler, text):
        message = FakeMessage(text, self.replies)
        update = SimpleNamespace(effective_message=message, effective_chat=SimpleNamespace(id=1),
                                 effective_user=SimpleNamespace(id=1))
        asyncio.run(self.callbacks[handler](update, SimpleNamespace(bot=FakeBot(), application=self.app, args=[])))
        return self.replies[-1]

    def test_a_research_verb_with_the_place_in_the_sentence_goes_straight_to_the_worker(self):
        reply = self.send("on_text", "pesquisa no Mind tudo sobre o Forge")
        self.assertIn("Passei ao Trabalhador", reply)
        self.assertIn("pesquisa no Mind tudo sobre o Forge", self.send("on_jobs", "/pedidos"))

    def test_without_the_place_it_asks_and_the_answer_decides(self):
        self.assertIn("No Mind ou por fora", self.send("on_text", "levanta as decisões sobre o domínio"))
        self.assertIn("Passei ao Trabalhador", self.send("on_text", "no mind"))
        self.assertIn("decisões sobre o domínio", self.send("on_jobs", "/pedidos"))

    def test_a_deep_internet_question_goes_to_the_worker_in_web_mode(self):
        self.send("on_text", "investiga e compara as opções de hospedagem")
        reply = self.send("on_text", "na internet")
        self.assertIn("pesquisa na internet", reply)
        self.assertIn("(internet)", self.send("on_jobs", "/pedidos"))

    def test_an_unrelated_message_closes_the_question(self):
        self.send("on_text", "procura o preço do dólar")
        self.send("on_text", "oi tudo bem?")
        self.assertNotIn("Passei", self.send("on_text", "mind"))

    def test_the_pede_command_and_an_empty_request(self):
        self.assertIn("Passei ao Trabalhador", self.send("on_ask", "/pede quantas notas tem no inbox?"))
        self.assertIn("O que devo pedir", self.send("on_ask", "/pede"))
