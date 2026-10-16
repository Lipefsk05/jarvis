"""The agenda conversation end to end: fake Telegram message, fake Google Calendar, the real flow and handlers."""
import asyncio
import importlib.util
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

HAS_TELEGRAM = importlib.util.find_spec("telegram") is not None
TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 16, 10, 0, tzinfo=TZ)  # a Friday


class FakeCalendar:
    """Stands in for GoogleCalendar: events per calendar id, every change recorded."""

    def __init__(self):
        self.events = {}
        self.fail = set()
        self.log = []
        self.counter = 0

    def add(self, calendar, title, start, minutes=60, event_id=None):
        from jarvis.gcal import Event
        self.counter += 1
        event = Event(event_id or f"e{self.counter}", calendar, title, start, start + timedelta(minutes=minutes))
        self.events.setdefault(calendar, []).append(event)
        return event

    def _check(self, calendar):
        from jarvis.gcal import CalendarError
        if calendar in self.fail:
            raise CalendarError("o Google respondeu 403", 403)

    def list_events(self, calendar, start, end):
        self._check(calendar)
        return [e for e in self.events.get(calendar, []) if e.start < end and e.end > start]

    def insert(self, calendar, title, start, end, location="", event_id=None):
        self._check(calendar)
        self.log.append(("insert", calendar, title, start, end))
        event = self.add(calendar, title, start, int((end - start).total_seconds() // 60), event_id)
        return event

    def move(self, calendar, event_id, start, end):
        self._check(calendar)
        self.log.append(("move", calendar, event_id, start, end))

    def delete(self, calendar, event_id):
        self._check(calendar)
        self.log.append(("delete", calendar, event_id))
        self.events[calendar] = [e for e in self.events.get(calendar, []) if e.id != event_id]


class FakeAssistant:
    def __init__(self):
        self.offered, self.remembered = None, []

    def offer(self, chat_id, action):
        self.offered = action

    def remember(self, chat_id, text):
        self.remembered.append(text)


class FakeMessage:
    def __init__(self, replies):
        self.replies = replies

    async def reply_text(self, text, reply_markup=None, **kwargs):
        self.replies.append((text, reply_markup))


@unittest.skipUnless(HAS_TELEGRAM, "python-telegram-bot not installed")
class AgendaBotTest(unittest.TestCase):
    def setUp(self):
        from jarvis.agenda import parse_accounts
        from jarvis.agenda_bot import AgendaHandlers
        from jarvis.agenda_flow import AgendaFlow
        from jarvis.agenda_service import Agenda

        self.accounts = parse_accounts("trabalho=a@x.com,pessoal=b@y.com,cafe=admin@cafelabs.net")
        self.calendar = FakeCalendar()
        self.assistant = FakeAssistant()
        self.replies = []
        self.handlers = AgendaHandlers(Agenda(self.calendar, self.accounts, lambda: NOW), AgendaFlow(self.accounts),
                                       self.assistant, lambda: NOW)

    def act(self, name, user_text="", **fields):
        from jarvis.actions import Action
        action = Action(name, **fields)
        asyncio.run(self.handlers.run(FakeMessage(self.replies), 1, action, user_text))
        return self.replies[-1][0]

    def reply(self, text):
        handled = asyncio.run(self.handlers.answer(FakeMessage(self.replies), 1, text))
        self.assertTrue(handled)
        return self.replies[-1][0]

    def at(self, hour, day=16):
        return datetime(2026, 10, day, hour, tzinfo=TZ)

    # reading
    def test_reading_merges_the_three_accounts_and_names_the_ones_that_failed(self):
        self.calendar.add("a@x.com", "Reunião Foo", self.at(15))
        self.calendar.add("admin@cafelabs.net", "reunião foo", self.at(15))
        self.calendar.add("b@y.com", "Dentista", self.at(9))
        self.calendar.fail.add("admin@cafelabs.net")
        text = self.act("consultar_agenda", quando="hoje")
        self.assertIn("• 09:00–10:00  Dentista (pessoal)", text)
        self.assertIn("Reunião Foo (profissional)", text)
        self.assertIn("Não consegui ler: Café Labs.", text)

    def test_reading_an_empty_day(self):
        self.assertEqual(self.act("consultar_agenda", quando="amanhã"), "Não há nada marcado amanhã, senhor.")

    # creating
    def test_creating_a_complete_event_uses_the_account_the_words_point_to(self):
        text = self.act("criar_evento", "marca reunião com o cliente amanhã às 15 na Café", texto="Reunião com o cliente",
                        quando="amanhã às 15")
        self.assertIn("Marcado, senhor", text)
        self.assertIn("agenda Café Labs", text)
        self.assertIn("deixei 1 h", text)
        kind, calendar, title, start, end = self.calendar.log[0]
        self.assertEqual((kind, calendar, start, end), ("insert", "admin@cafelabs.net", self.at(15, 17), self.at(16, 17)))
        self.assertIsNotNone(self.replies[-1][1])  # the Desfazer button

    def test_an_unknown_account_is_asked_and_the_answer_creates_it(self):
        self.assertIn("Em qual agenda", self.act("criar_evento", "marca almoço amanhã às 12", texto="Almoço", quando="amanhã às 12"))
        self.assertEqual(self.calendar.log, [])
        self.assertIn("agenda pessoal", self.reply("pessoal"))
        self.assertEqual(self.calendar.log[0][1], "b@y.com")

    def test_a_clash_asks_and_the_yes_creates_exactly_what_was_proposed(self):
        self.calendar.add("a@x.com", "Treino", self.at(15, 17))
        text = self.act("criar_evento", "marca dentista amanhã às 15 pessoal", texto="Dentista", quando="amanhã às 15")
        self.assertIn("Já há “Treino”", text)
        self.assertEqual(self.calendar.log, [])
        self.act(self.assistant.offered.name, **{k: v for k, v in vars(self.assistant.offered).items() if k != "name"})
        self.assertEqual([entry[0] for entry in self.calendar.log], ["insert"])
        self.assertEqual(self.calendar.log[0][1], "b@y.com")

    def test_the_google_refusal_is_explained(self):
        self.calendar.fail.add("b@y.com")
        text = self.act("criar_evento", "marca dentista amanhã às 15 pessoal", texto="Dentista", quando="amanhã às 15")
        self.assertIn("não está compartilhada", text)

    # cancelling and moving
    def test_cancelling_asks_first_and_deletes_every_copy(self):
        self.calendar.add("a@x.com", "Reunião Foo", self.at(15, 17), event_id="ea")
        self.calendar.add("admin@cafelabs.net", "Reunião Foo", self.at(15, 17), event_id="ec")
        question = self.act("cancelar_evento", busca="reunião foo")
        self.assertIn("Apago “Reunião Foo”", question)
        self.assertIn("profissional e Café Labs", question)
        self.assertEqual(self.calendar.log, [])
        offered = self.assistant.offered
        self.act("cancelar_evento", ref=offered.ref, texto=offered.texto)
        self.assertEqual(sorted(e[1:] for e in self.calendar.log), [("a@x.com", "ea"), ("admin@cafelabs.net", "ec")])

    def test_cancelling_something_that_is_not_there_or_is_ambiguous(self):
        self.assertIn("Não achei", self.act("cancelar_evento", busca="dentista"))
        self.calendar.add("a@x.com", "Reunião Foo", self.at(15, 17))
        self.calendar.add("a@x.com", "Reunião Bar", self.at(16, 17))
        self.assertIn("mais de um", self.act("cancelar_evento", busca="reunião"))

    def test_moving_keeps_the_length_and_asks_first(self):
        self.calendar.add("a@x.com", "Dentista", self.at(14, 17), minutes=90, event_id="ed")
        question = self.act("mover_evento", "muda o dentista pra segunda às 10", busca="dentista", quando="segunda às 10")
        self.assertIn("Movo “Dentista”", question)
        self.assertEqual(self.calendar.log, [])
        offered = self.assistant.offered
        self.act("mover_evento", ref=offered.ref, texto=offered.texto, quando=offered.quando, duracao=offered.duracao)
        kind, calendar, event_id, start, end = self.calendar.log[0]
        self.assertEqual((kind, event_id, start, end - start), ("move", "ed", self.at(10, 19), timedelta(minutes=90)))

    def test_a_whole_sentence_is_enough_the_code_reads_title_day_and_hour(self):
        asked = self.act("criar_evento", "Marca amanhã uma reunião com o cliente às 15", texto="", quando="")
        self.assertIn("Em qual agenda", asked)
        self.assertEqual(self.calendar.log, [])
        self.assertIn("agenda Café Labs", self.reply("Café"))  # the answer marks it, no second question
        kind, calendar, title, start, end = self.calendar.log[0]
        self.assertEqual((calendar, title, start), ("admin@cafelabs.net", "Reunião com o cliente", self.at(15, 17)))

    def test_two_events_in_one_sentence_create_nothing_and_say_so(self):
        text = self.act("criar_evento", "Marca uma reunião hoje às 16 e outra às 22", texto="", quando="")
        self.assertIn("um evento por vez", text)
        self.assertEqual(self.calendar.log, [])

    def test_undo_button_deletes_the_new_event(self):
        self.act("criar_evento", "marca reunião com o cliente amanhã às 15 na Café", texto="Reunião", quando="amanhã às 15")
        data = self.replies[-1][1].inline_keyboard[0][0].callback_data
        answers = []

        class Query:
            def __init__(self):
                self.data, self.message = data, SimpleNamespace(text="Marcado.")

            async def answer(self, text="", **kwargs):
                answers.append(text)

            async def edit_message_text(self, text, **kwargs):
                answers.append(text)

        asyncio.run(self.handlers.undo(SimpleNamespace(callback_query=Query()), None))
        self.assertEqual(self.calendar.log[-1][0], "delete")
        self.assertIn("Desfeito, senhor.", answers)


if __name__ == "__main__":
    unittest.main()
