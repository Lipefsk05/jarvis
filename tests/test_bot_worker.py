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

    def test_a_research_verb_queues_a_job(self):
        reply = self.send("on_text", "pesquisa no Mind tudo sobre o Forge")
        self.assertIn("Passei ao Trabalhador", reply)
        self.assertIn("pesquisa no Mind tudo sobre o Forge", self.send("on_jobs", "/pedidos"))

    def test_the_pede_command_and_an_empty_request(self):
        self.assertIn("Passei ao Trabalhador", self.send("on_ask", "/pede quantas notas tem no inbox?"))
        self.assertIn("O que devo pedir", self.send("on_ask", "/pede"))
