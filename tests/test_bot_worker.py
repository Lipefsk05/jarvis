"""A research verb in a plain message reaches the Worker end to end, with no model call; /pedidos shows it."""
import unittest

from jarvis import research
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
        self.assertIn(reply, research.ACKS)
        self.assertNotIn("Forge", reply)  # the request is not echoed back
        self.assertIn("pesquisa no Mind tudo sobre o Forge", self.send("on_jobs", "/pedidos"))

    def test_a_question_about_live_data_goes_to_the_internet_without_a_verb_and_without_asking(self):
        for text in ("Qual a cotação do dólar atual?", "quem ganhou o jogo ontem?"):
            reply = self.send("on_text", text)
            self.assertNotIn("Mind ou", reply)
            self.assertNotIn("não tenho certeza", reply.lower())

    def test_without_the_place_it_asks_and_the_answer_decides(self):
        self.assertIn("No Mind ou por fora", self.send("on_text", "levanta as decisões sobre o domínio"))
        self.assertIn(self.send("on_text", "no mind"), research.ACKS)
        self.assertIn("decisões sobre o domínio", self.send("on_jobs", "/pedidos"))

    def test_a_deep_internet_question_goes_to_the_worker_in_web_mode(self):
        self.send("on_text", "investiga e compara as opções de hospedagem")
        reply = self.send("on_text", "na internet")
        self.assertIn(reply, research.ACKS)
        self.assertIn("(internet)", self.send("on_jobs", "/pedidos"))

    def test_an_unrelated_message_closes_the_question(self):
        self.send("on_text", "procura o preço do dólar")
        self.send("on_text", "oi tudo bem?")
        self.assertNotIn("Passei", self.send("on_text", "mind"))

    def test_the_pede_command_and_an_empty_request(self):
        self.assertIn(self.send("on_ask", "/pede quantas notas tem no inbox?"), research.ACKS)
        self.assertIn("O que devo pesquisar", self.send("on_ask", "/pede"))

    def test_compara_and_olha_pra_mim_start_a_research_and_no_reply_names_the_tool(self):
        for text in ("Compara pra mim firebase e supabase na internet", "olha pra mim quanto custa o domínio .com.br"):
            reply = self.send("on_text", text)
            self.assertNotIn("Trabalhador", reply)
