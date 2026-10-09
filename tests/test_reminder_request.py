import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.reminder_request import Planned, plan_reminder, split_request
from jarvis.when import Ask

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 9, 11, 0, tzinfo=TZ)  # sexta-feira


def at(day, month, hour, minute=0):
    return datetime(2026, month, day, hour, minute, tzinfo=TZ)


class SplitTest(unittest.TestCase):
    def check(self, raw, text, phrase_has, lead=0):
        got_text, phrase, got_lead = split_request(raw)
        self.assertEqual(got_text, text, raw)
        self.assertEqual(got_lead, lead, raw)
        for word in phrase_has:
            self.assertIn(word, phrase, raw)

    def test_when_first(self):
        self.check("amanhã às 9 pagar o aluguel", "pagar o aluguel", ["amanha", "as", "9"])
        self.check("daqui a 2 horas tirar o bolo do forno", "tirar o bolo do forno", ["daqui", "2", "horas"])
        self.check("sexta 15h reunião com o time", "reunião com o time", ["sexta", "15h"])

    def test_when_last(self):
        self.check("pagar o aluguel amanhã às 9", "pagar o aluguel", ["amanha", "9"])
        self.check("ligar pro João em 20 minutos", "ligar pro João", ["20", "minutos"])

    def test_when_in_the_middle(self):
        self.check("ligar pro João amanhã às 9 sobre o contrato", "ligar pro João sobre o contrato", ["amanha", "9"])

    def test_connectors_go_back_to_the_text(self):
        self.check("me lembra de pagar a luz amanhã às 9", "me lembra de pagar a luz", ["amanha", "9"])
        self.check("reunião de amanhã às 9", "reunião", ["amanha", "9"])
        self.check("amanhã às 9 em casa fazer a prova", "em casa fazer a prova", ["amanha", "9"])

    def test_articles_left_at_the_start_of_the_text_are_dropped(self):
        self.check("sexta 15h da reunião com o time", "reunião com o time", ["sexta", "15h"])
        self.check("amanhã às 8 do remédio", "remédio", ["amanha", "8"])

    def test_words_that_look_like_time_but_are_not(self):
        text, phrase, _ = split_request("comprar 2 pães e chegar tarde em casa")
        self.assertEqual(phrase, "")  # no day, no hour: not a time
        text, phrase, _ = split_request("bom dia para a Ana, ligar de tarde")
        self.assertEqual(phrase, "")

    def test_lead_forms(self):
        self.check("amanhã às 9 consulta, 10 min antes", "consulta", ["amanha"], 10)
        self.check("amanhã às 9 consulta uns 15 minutos antes", "consulta", ["amanha"], 15)
        self.check("amanhã às 9 consulta meia hora antes", "consulta", ["amanha"], 30)
        self.check("amanhã às 9 consulta 1h antes", "consulta", ["amanha"], 60)
        self.check("amanhã às 9 consulta uma hora antes", "consulta", ["amanha"], 60)
        self.check("amanhã às 9 consulta 10min antes", "consulta", ["amanha"], 10)

    def test_pipe_separator_gives_exact_control(self):
        self.check("amanhã às 9 | pagar 3 boletos de tarde", "pagar 3 boletos de tarde", ["amanha", "9"])
        self.check("pagar 3 boletos de tarde | amanhã às 9", "pagar 3 boletos de tarde", ["amanha", "9"])


class PlanTest(unittest.TestCase):
    def test_simple_reminder(self):
        plan = plan_reminder("amanhã às 9 pagar o aluguel", NOW)
        self.assertEqual(plan, Planned("pagar o aluguel", at(10, 10, 9), None, 0, False))

    def test_with_advance_warning(self):
        plan = plan_reminder("hoje às 19 pg jovem, 10 min antes", NOW)
        self.assertEqual(plan.text, "pg jovem")
        self.assertEqual(plan.event, at(9, 10, 19))
        self.assertEqual(plan.due, at(9, 10, 18, 50))
        self.assertEqual(plan.lead_minutes, 10)

    def test_advance_warning_that_already_passed_is_questioned(self):
        result = plan_reminder("daqui a 5 minutos reunião 10 min antes", NOW)
        self.assertEqual(result.kind, "passou")
        self.assertIn("10 minutos", result.question)

    def test_default_hour_is_flagged(self):
        plan = plan_reminder("amanhã pagar o aluguel", NOW, default_hour=9)
        self.assertEqual((plan.due, plan.hour_assumed), (at(10, 10, 9), True))
        self.assertEqual(plan_reminder("amanhã pagar o aluguel", NOW).kind, "hora")

    def test_missing_pieces_are_questioned(self):
        self.assertEqual(plan_reminder("pagar o aluguel", NOW).kind, "entendi")
        self.assertEqual(plan_reminder("amanhã às 9", NOW).kind, "texto")
        self.assertEqual(plan_reminder("", NOW).kind, "entendi")
        self.assertEqual(plan_reminder("amanhã às 9 consulta 99 horas antes", NOW).kind, "invalido")

    def test_invalid_time_inside_a_sentence_is_questioned(self):
        self.assertIsInstance(plan_reminder("31/02 às 9 aniversário", NOW), Ask)
