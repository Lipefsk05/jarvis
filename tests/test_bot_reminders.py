"""The bot's reminder conversation end to end, with fake Telegram messages (no network, no model):
the question the bot asks, the answer that completes it, and what is stored."""
import asyncio
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HAS_TELEGRAM = importlib.util.find_spec("telegram") is not None


class FakeMessage:
    def __init__(self, text, replies):
        self.text = text
        self._replies = replies
        self.date = None

    async def reply_text(self, text, **kwargs):
        self._replies.append(text)


class FakeBot:
    async def send_chat_action(self, *args, **kwargs):
        return None


class _BotCase(unittest.TestCase):
    def setUp(self):
        from jarvis.bot import build_application
        from jarvis.config import Settings

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name)
        settings = Settings.load(env_path=self.state / "no.env", environ={
            "TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_ALLOWED_USER_IDS": "1", "JARVIS_TALKER_PROVIDER": "groq",
            "GROQ_API_KEY": "k", "JARVIS_DAILY_BUDGET_USD": "1", "JARVIS_STATE_DIR": str(self.state),
            "JARVIS_MIND_DIR": str(self.state), "JARVIS_INBOX_DIR": str(self.state / "inbox"),
        })
        self.app = build_application(settings)
        callbacks = {h.callback.__name__: h.callback for group in self.app.handlers.values() for h in group
                     if hasattr(h, "callback")}
        self.on_text, self.on_remind = callbacks["on_text"], callbacks["on_remind"]
        self.on_list = callbacks["on_reminders"]
        self.replies = []

    def say(self, handler, text):
        message = FakeMessage(text, self.replies)
        update = SimpleNamespace(effective_message=message, effective_chat=SimpleNamespace(id=1),
                                 effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(bot=FakeBot(), application=self.app, args=[])
        asyncio.run(handler(update, context))
        return self.replies[-1]

    def text(self, message):
        return self.say(self.on_text, message)

    def stored(self):
        path = self.state / "lembretes.json"
        if not path.exists():
            return []
        return [i for i in json.loads(path.read_text(encoding="utf-8"))["items"] if i["status"] == "pendente"]



@unittest.skipUnless(HAS_TELEGRAM, "python-telegram-bot not installed")
class BotReminderConversationTest(_BotCase):
    def test_complete_request_is_marked_at_once(self):
        self.assertIn("Marcado", self.text("me lembra amanhã às 9 de ligar pro Carlos"))
        self.assertEqual([i["text"] for i in self.stored()], ["ligar pro Carlos"])

    def test_missing_hour_is_asked_then_marked(self):
        self.assertIn("Que horas", self.text("me lembra de buscar o bolo amanhã"))
        self.assertEqual(self.stored(), [])  # nothing is stored while a question is open
        self.assertIn("Marcado", self.text("às 8"))
        self.assertEqual([(i["text"], i["due"][11:16]) for i in self.stored()], [("buscar o bolo", "08:00")])

    def test_part_of_the_day_asks_which_hour(self):
        self.assertIn("Que horas da tarde", self.text("me lembra amanhã à tarde de buscar o bolo"))
        self.assertIn("Marcado", self.text("três e meia"))
        self.assertEqual([i["due"][11:16] for i in self.stored()], ["15:30"])

    def test_routine_asks_whether_to_repeat_and_repeats_on_request(self):
        self.assertIn("rotina", self.text("me lembra de tomar remédio amanhã às 8"))
        self.assertIn("Repito", self.text("todo dia"))
        self.assertEqual([i["repeat"] for i in self.stored()], ["daily"])

    def test_routine_once_only(self):
        self.text("me lembra de tomar remédio amanhã às 8")
        self.assertIn("Marcado", self.text("só dessa vez"))
        self.assertEqual([i["repeat"] for i in self.stored()], [None])

    def test_schedule_sentence_needs_no_opening_and_makes_one_per_day(self):
        reply = self.text("Toda terça e sexta academia as 15")
        self.assertIn("lembretes", reply)
        self.assertEqual(sorted(i["due"][11:16] for i in self.stored()), ["15:00", "15:00"])
        self.assertEqual({i["repeat"] for i in self.stored()}, {"weekly"})

    def test_giving_up_stores_nothing(self):
        self.text("me lembra de ligar pro joão amanhã")
        self.assertIn("não marquei nada", self.text("deixa pra lá"))
        self.assertEqual(self.stored(), [])

    def test_the_lembra_command_goes_through_the_same_questions(self):
        self.assertIn("Que horas", self.say(self.on_remind, "/lembra amanhã ligar pro joão"))
        self.assertIn("Marcado", self.text("10"))
        self.assertEqual([i["due"][11:16] for i in self.stored()], ["10:00"])

    def test_two_hours_in_one_sentence_is_refused(self):
        self.assertIn("mais de um dia ou horário", self.text("me lembra amanhã às 9 e às 15 de ligar"))
        self.assertEqual(self.stored(), [])

    def test_a_series_is_all_or_nothing(self):
        self.text("me lembra toda segunda e quarta às 7 de enviar o relatório")
        self.assertEqual(len(self.stored()), 2)


@unittest.skipUnless(HAS_TELEGRAM, "python-telegram-bot not installed")
class BotClashTest(_BotCase):
    """The Felipe's own example: training at 9 for two hours, then something at 10."""

    def training(self):
        self.assertIn("rotina", self.text("me lembra amanhã às 9 de treinar por 2 horas"))
        reply = self.text("só dessa vez")
        self.assertIn("Marcado", reply)
        self.assertIn("Dura 2 horas", reply)

    def test_the_duration_is_stored_and_listed(self):
        self.training()
        self.assertEqual([i["duration"] for i in self.stored()], [120])
        self.assertIn("dura 2 horas", self.say(self.on_list, "/lembretes"))

    def test_a_clash_is_asked_before_marking_and_yes_marks(self):
        self.training()
        question = self.text("me lembra amanhã às 10 de ligar pro Pedro")
        self.assertIn("“treinar” vai de 09:00 até 11:00", question)
        self.assertIn("Marco mesmo assim", question)
        self.assertEqual(len(self.stored()), 1)  # nothing stored while the question is open
        self.assertIn("Marcado", self.text("sim"))
        self.assertEqual(sorted(i["text"] for i in self.stored()), ["ligar pro Pedro", "treinar"])

    def test_no_marks_nothing(self):
        self.training()
        self.text("me lembra amanhã às 10 de ligar pro Pedro")
        self.assertIn("não marquei nada", self.text("não"))
        self.assertEqual([i["text"] for i in self.stored()], ["treinar"])

    def test_another_time_that_fits_is_marked(self):
        self.training()
        self.text("me lembra amanhã às 10 de ligar pro Pedro")
        self.assertIn("Marcado", self.text("às 11"))
        self.assertEqual(sorted(i["due"][11:16] for i in self.stored()), ["09:00", "11:00"])

    def test_close_events_without_a_duration_ask_whether_they_fit(self):
        self.text("me lembra amanhã às 9 de ligar pro Carlos")
        question = self.text("me lembra amanhã às 10 de ligar pro Pedro")
        self.assertIn("Dá tempo dos dois", question)

    def test_events_far_apart_are_marked_without_a_question(self):
        self.text("me lembra amanhã às 9 de ligar pro Carlos")
        self.assertIn("Marcado", self.text("me lembra amanhã às 15 de ligar pro Pedro"))


@unittest.skipUnless(HAS_TELEGRAM, "python-telegram-bot not installed")
class BotVoiceAndGatesTest(_BotCase):
    """What went wrong on the phone with voice: "Me lembro" for "Me lembra", and the model calling a tool nobody asked for."""

    def model_calls(self, name, **arguments):
        from unittest import mock

        from jarvis.talker.base import Reply, ToolCall
        from jarvis.talker.groq_provider import GroqTalker

        call = ToolCall(name, arguments)
        return mock.patch.object(GroqTalker, "reply", lambda self, system, messages, tools=None: Reply("", 10, 5, tool_call=call))

    def test_me_lembro_with_a_time_is_a_reminder_request(self):
        # no model is faked here: a call to the model would fail the test (401), so it must be handled by code
        for said in ("Me lembro amanhã às nove de ligar pro Carlos.", "Me lembro amanhã às 15 de ligar pro Carlos."):
            with self.subTest(said):
                self.assertIn("Marcado", self.text(said))
        self.assertEqual(len(self.stored()), 2)

    def test_the_voice_example_asks_if_it_repeats(self):
        self.assertIn("rotina", self.text("Me lembro amanhã às nove de treinar por duas horas."))
        self.assertIn("Dura 2 horas", self.text("só dessa vez"))

    def test_a_garbled_hour_is_asked_not_guessed(self):
        self.assertIn("Que horas", self.text("Me lembra amanhã as ideias de ligar pro Carlos?"))
        self.assertEqual(self.stored(), [])

    def test_the_model_cancelling_without_being_asked_only_gets_a_question(self):
        self.text("me lembra amanhã às 15 de ligar pro Carlos")
        with self.model_calls("cancelar_lembrete", numero=1):
            reply = self.text("treinar amanhã de manhã")
        self.assertIn("Quer que eu cancele o lembrete 1", reply)
        self.assertEqual(len(self.stored()), 1)  # nothing was cancelled
        self.assertIn("cancelado", self.text("sim").lower())
        self.assertEqual(self.stored(), [])

    def test_cancelling_when_the_user_asked_is_done_at_once(self):
        self.text("me lembra amanhã às 15 de ligar pro Carlos")
        with self.model_calls("cancelar_lembrete", numero=1):
            self.text("cancela o lembrete 1")
        self.assertEqual(self.stored(), [])

    def test_listing_without_being_asked_is_not_done(self):
        with self.model_calls("listar_lembretes"):
            reply = self.text("banana")
        self.assertIn("Não tenho certeza", reply)

    def test_listing_when_asked_is_done(self):
        with self.model_calls("listar_lembretes"):
            reply = self.text("quais são meus lembretes?")
        self.assertIn("Não há lembretes", reply)

    def test_a_note_nobody_asked_for_becomes_an_offer(self):
        with self.model_calls("anotar", texto="comprar pão"):
            reply = self.text("o pão acabou")
        self.assertIn("Quer que eu anote", reply)
        self.assertFalse(list((self.state / "inbox").glob("*")) if (self.state / "inbox").exists() else [])


@unittest.skipUnless(HAS_TELEGRAM, "python-telegram-bot not installed")
class BotModelPathTest(_BotCase):
    """The model (faked here) calls `criar_lembrete`; the bot must still read the time from the user's words."""

    def model_says(self, texto, quando, antecedencia=None):
        from unittest import mock

        from jarvis.talker.base import Reply, ToolCall
        from jarvis.talker.groq_provider import GroqTalker

        call = ToolCall("criar_lembrete", {"texto": texto, "quando": quando, "antecedencia_minutos": antecedencia})
        return mock.patch.object(GroqTalker, "reply", lambda self, system, messages, tools=None: Reply("", 10, 5, tool_call=call))

    def test_model_that_dropped_days_and_hour(self):
        with self.model_says("ir na aula de inglês", "toda terça"):
            reply = self.text("Pode lembrar todas as terças e quintas de ir na aula de inglês às duas da tarde?")
        self.assertIn("lembretes", reply)
        self.assertEqual(sorted(i["due"][11:16] for i in self.stored()), ["14:00", "14:00"])

    def test_model_that_invented_an_hour_is_not_believed(self):
        with self.model_says("buscar o bolo", "amanhã às 9"):
            reply = self.text("me avisa amanhã do bolo")
        self.assertIn("Que horas", reply)
        self.assertEqual(self.stored(), [])
        self.assertIn("Marcado", self.text("às 10"))
        self.assertEqual([(i["text"], i["due"][11:16]) for i in self.stored()], [("buscar o bolo", "10:00")])

    def test_remark_becomes_an_offer_and_a_yes_asks_the_missing_hour(self):
        with self.model_says("dentista", "amanhã"):
            offer = self.text("tenho dentista amanhã")
        self.assertIn("Quer que eu o avise", offer)
        self.assertEqual(self.stored(), [])
        self.assertIn("Que horas", self.text("sim"))
        self.assertIn("Marcado", self.text("às 14"))
        self.assertEqual([(i["text"], i["due"][11:16]) for i in self.stored()], [("dentista", "14:00")])

    def test_model_text_that_is_a_routine_asks_to_repeat(self):
        with self.model_says("tomar remédio", "amanhã às 8"):
            reply = self.text("me avisa amanhã às 8 do remédio")
        self.assertIn("rotina", reply)
        self.assertIn("Marcado", self.text("não"))


if __name__ == "__main__":
    unittest.main()
