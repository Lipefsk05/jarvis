import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from jarvis.agenda import parse_accounts
from jarvis.agenda_flow import CANCELLED, TTL, AgendaFlow, Plan
from jarvis.when import Ask

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 16, 10, 0, tzinfo=TZ)  # a Friday
ACCOUNTS = parse_accounts("trabalho=a@x.com,pessoal=b@y.com,cafe=admin@cafelabs.net")


def start(flow, said, title="", when="", minutes=0, hint="", chat=1, now=NOW):
    return flow.start(chat, said, title, when, minutes, hint, now)


class CreateTest(unittest.TestCase):
    def setUp(self):
        self.flow = AgendaFlow(ACCOUNTS)

    def test_the_account_is_always_asked_even_when_the_subject_points_to_one(self):
        ask = start(self.flow, "marca reunião com o cliente amanhã às 15", "Reunião com o cliente", "amanhã às 15")
        self.assertEqual(ask.kind, "conta")
        plan = self.flow.answer(1, "Café", NOW)  # the answer creates it: no second question
        self.assertIsInstance(plan, Plan)
        self.assertEqual(plan.account.key, "cafe")
        self.assertFalse(self.flow.pending(1))

    def test_an_account_named_in_the_sentence_is_not_asked_again(self):
        plan = start(self.flow, "marca reunião com o cliente amanhã às 15 na Café", "Reunião com o cliente", "amanhã às 15")
        self.assertIsInstance(plan, Plan)
        self.assertEqual(plan.account.key, "cafe")
        self.assertEqual((plan.start, plan.end), (datetime(2026, 10, 17, 15, tzinfo=TZ), datetime(2026, 10, 17, 16, tzinfo=TZ)))
        self.assertTrue(plan.assumed_length)

    def test_the_length_comes_from_the_owners_words_first_then_the_model(self):
        said = start(self.flow, "marca dentista amanhã às 14 por 2 horas pessoal", "Dentista", "amanhã às 14", 30)
        self.assertEqual(said.end - said.start, timedelta(hours=2))
        self.assertFalse(said.assumed_length)
        model = start(self.flow, "marca dentista amanhã às 14 pessoal", "Dentista", "amanhã às 14", 45)
        self.assertEqual(model.end - model.start, timedelta(minutes=45))
        self.assertFalse(model.assumed_length)

    def test_asks_for_the_hour_and_then_finishes(self):
        ask = start(self.flow, "marca dentista amanhã pessoal", "Dentista", "amanhã")
        self.assertIsInstance(ask, Ask)
        self.assertTrue(self.flow.pending(1))
        plan = self.flow.answer(1, "às 14", NOW)
        self.assertIsInstance(plan, Plan)
        self.assertEqual(plan.start, datetime(2026, 10, 17, 14, tzinfo=TZ))
        self.assertFalse(self.flow.pending(1))

    def test_never_guesses_the_account_it_asks_and_takes_the_answer(self):
        ask = start(self.flow, "marca almoço amanhã às 12", "Almoço", "amanhã às 12")
        self.assertEqual(ask.kind, "conta")
        again = self.flow.answer(1, "sei lá", NOW)
        self.assertEqual(again.kind, "conta")
        plan = self.flow.answer(1, "na pessoal", NOW)
        self.assertEqual(plan.account.key, "pessoal")

    def test_a_cancel_word_drops_the_question(self):
        start(self.flow, "marca almoço amanhã às 12", "Almoço", "amanhã às 12")
        self.assertEqual(self.flow.answer(1, "não, deixa", NOW), CANCELLED)
        self.assertIsNone(self.flow.answer(1, "pessoal", NOW))

    def test_an_old_question_is_forgotten(self):
        start(self.flow, "marca almoço amanhã às 12", "Almoço", "amanhã às 12")
        self.assertIsNone(self.flow.answer(1, "pessoal", NOW + TTL + timedelta(minutes=1)))

    def test_a_time_in_the_past_asks_again(self):
        ask = start(self.flow, "marca dentista hoje às 8", "Dentista", "hoje às 8")
        self.assertEqual(ask.kind, "passou")

    def test_repeating_events_are_refused_with_a_way_out(self):
        ask = start(self.flow, "marca academia toda segunda às 7", "Academia", "toda segunda às 7")
        self.assertEqual(ask.kind, "recorrente")
        self.assertFalse(self.flow.pending(1))

    def test_each_chat_has_its_own_question(self):
        start(self.flow, "marca almoço amanhã às 12", "Almoço", "amanhã às 12", chat=1)
        self.assertIsNone(self.flow.answer(2, "pessoal", NOW))
        self.assertTrue(self.flow.pending(1))


if __name__ == "__main__":
    unittest.main()


class TitleAndManyTest(unittest.TestCase):
    def test_title_out_of_a_whole_sentence(self):
        from jarvis.agenda_flow import title_from_words
        cases = {
            "Marca amanhã uma reunião às 15": "Reunião",
            "marca reunião com o cliente amanhã às 11": "Reunião com o cliente",
            "marca dentista amanhã às 14 por 2 horas na pessoal": "Dentista",
            "põe na agenda almoço com a Ana sexta às 12 da Café": "Almoço com a Ana",
            "agenda uma consulta dia 20 às 10:30 pessoal": "Consulta",
        }
        for said, title in cases.items():
            self.assertEqual(title_from_words(said), title, said)

    def test_a_request_by_sentence_needs_no_model_title(self):
        flow = AgendaFlow(ACCOUNTS)
        ask = flow.start(1, "marca reunião com o cliente amanhã às 15", "", "", 0, "", NOW)
        self.assertEqual(ask.kind, "conta")
        plan = flow.answer(1, "Café", NOW)
        self.assertEqual((plan.title, plan.account.key), ("Reunião com o cliente", "cafe"))

    def test_two_events_in_one_sentence_are_refused_out_loud_not_dropped(self):
        flow = AgendaFlow(ACCOUNTS)
        for said in ("Marca uma reunião hoje às 16 e outra às 22", "marca amanhã uma reunião às 11 e outra às 19"):
            ask = flow.start(1, said, "", "", 0, "", NOW)
            self.assertEqual(ask.kind, "varios", said)
            self.assertFalse(flow.pending(1))
