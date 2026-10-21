"""/plano end to end with a tiny Mind on disk: the calendar is built from the board and persisted."""
import json
import unittest

from test_bot_reminders import HAS_TELEGRAM, SimpleNamespace, _BotCase, FakeBot, FakeMessage, asyncio


@unittest.skipUnless(HAS_TELEGRAM, "python-telegram-bot not installed")
class BotPlanTest(_BotCase):
    def setUp(self):
        super().setUp()
        folder = self.state / "tarefas" / "pessoal"
        folder.mkdir(parents=True)
        (folder / "casa.md").write_text("## Geral\n- [ ] 🔴 Pagar o aluguel ^aluguel\n- [ ] 🟡 Trocar a lâmpada\n", encoding="utf-8")
        callbacks = {h.callback.__name__: h.callback for group in self.app.handlers.values() for h in group
                     if hasattr(h, "callback")}
        self.on_plan = callbacks["on_plan"]
        self.on_capacity = callbacks["on_capacity"]

    def ask(self, *args):
        message = FakeMessage("/plano", self.replies)
        update = SimpleNamespace(effective_message=message, effective_chat=SimpleNamespace(id=1),
                                 effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(bot=FakeBot(), application=self.app, args=list(args))
        asyncio.run(self.on_plan(update, context))
        return self.replies[-1]

    def set_capacity(self, *args):
        message = FakeMessage("/capacidade", self.replies)
        update = SimpleNamespace(effective_message=message, effective_chat=SimpleNamespace(id=1),
                                 effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(bot=FakeBot(), application=self.app, args=list(args))
        asyncio.run(self.on_capacity(update, context))
        return self.replies[-1]

    def test_capacidade_sets_a_fixed_number_shows_it_and_auto_gives_it_back(self):
        self.assertIn("3 por dia útil, aprendidas", self.set_capacity())
        self.assertIn("4 tarefa(s) por dia útil, fixas", self.set_capacity("4"))
        saved = json.loads((self.state / "plano.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["load"]["fixed"], 4)
        self.assertIn("4 por dia útil, fixas", self.set_capacity())
        self.assertIn("aprender sozinho", self.set_capacity("auto"))
        saved = json.loads((self.state / "plano.json").read_text(encoding="utf-8"))
        self.assertIsNone(saved["load"]["fixed"])

    def test_capacidade_rejects_nonsense(self):
        self.assertIn("de 1 a 10", self.set_capacity("0"))
        self.assertIn("de 1 a 10", self.set_capacity("muitas"))

    def test_plan_lists_the_board_tasks_by_priority_and_is_saved(self):
        reply = self.ask()
        self.assertIn("Pagar o aluguel", reply)
        self.assertLess(reply.index("Pagar o aluguel"), reply.index("Trocar a lâmpada"))
        saved = json.loads((self.state / "plano.json").read_text(encoding="utf-8"))
        self.assertTrue(saved["days"])
        self.assertEqual(saved["load"]["base"], 3)

    def test_asking_again_keeps_the_same_day(self):
        first = self.ask()
        self.assertEqual(self.ask(), first)

    def test_week_view(self):
        self.assertIn("Próximos dias", self.ask("semana"))
