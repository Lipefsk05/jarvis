"""Regression corpus: real-sounding "me lembra ..." sentences and what each must become.
Each sentence that went wrong on the phone is added here with the right answer."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.commands import parse_reminder_request
from jarvis.reminder_request import Planned, PlannedSeries, plan_reminder
from jarvis.when import Ask

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 11, 15, 0, tzinfo=TZ)  # domingo

# sentence -> (text, day, month, hour, minute, repeat)
PLANNED = {
    "me lembra de ligar pro joão amanhã de manhã": ("ligar pro joão", 12, 10, 9, 0, None),
    "me lembra amanhã cedo de pagar a luz": ("pagar a luz", 12, 10, 7, 0, None),
    "me lembra amanhã de tarde de buscar o bolo": ("buscar o bolo", 12, 10, 15, 0, None),
    "me lembra hoje à noite de ligar pra minha mãe": ("ligar pra minha mãe", 11, 10, 20, 0, None),
    "me lembra de manhã de tomar vitamina": ("tomar vitamina", 12, 10, 9, 0, None),
    "me lembra em 1 hora e meia de ver o bolo": ("ver o bolo", 11, 10, 16, 30, None),
    "me lembra daqui a duas horas e meia de ver o bolo": ("ver o bolo", 11, 10, 17, 30, None),
    "me lembra às nove da noite de fechar o caixa": ("fechar o caixa", 11, 10, 21, 0, None),
    "me lembra de orar todo dia ao meio dia": ("orar", 12, 10, 12, 0, "daily"),
    "me lembra todos os dias as 13: Oração": ("Oração", 12, 10, 13, 0, "daily"),
    "me lembra na sexta que vou ao médico às 14h": ("vou ao médico", 16, 10, 14, 0, None),
    "me lembra sábado que vem de comprar presente": ("comprar presente", 17, 10, 9, 0, None),
    "me lembra às 8:30 da manhã de amanhã de tomar remédio": ("tomar remédio", 12, 10, 8, 30, None),
    "me lembra toda segunda a sexta às 7 da manhã de treinar": ("treinar", 12, 10, 7, 0, "weekdays"),
    "me lembra do dentista amanhã às 14": ("dentista", 12, 10, 14, 0, None),
    # as the audio transcription writes them: question mark at the end, "uma", "à tarde", "às sete da manhã"
    "Me lembra em uma hora e meia de ver o bolo?": ("ver o bolo", 11, 10, 16, 30, None),
    "Me lembra amanhã à tarde de buscar o bolo?": ("buscar o bolo", 12, 10, 15, 0, None),
}
# sentence -> the kind of question the code must ask instead of guessing
ASKED = {
    "me lembra de a cada 2 horas beber água": "repeticao",
    "me lembra de 2 em 2 horas de beber água": "repeticao",
    "me lembra todo mês dia 5 de pagar o cartão": "repeticao",
    "me lembra semana que vem de ligar pro Matheus": "entendi",
}


# sentence -> (text, [(day, month, hour, minute), ...]): one weekly reminder per weekday
SERIES = {
    "me lembra toda segunda e quarta às 7 de treinar": ("treinar", [(12, 10, 7, 0), (14, 10, 7, 0)]),
    "Pode me lembrar toda segunda e quarta de manhã, às sete da manhã, treinar?": ("treinar", [(12, 10, 7, 0), (14, 10, 7, 0)]),
    "me lembra todo sábado e domingo às 10 de correr": ("correr", [(17, 10, 10, 0), (18, 10, 10, 0)]),
    "me lembra toda segunda, terça, quarta, quinta, sexta e sábado às 7 da manhã de treinar": ("treinar", [(12, 10, 7, 0), (13, 10, 7, 0), (14, 10, 7, 0), (15, 10, 7, 0), (16, 10, 7, 0), (17, 10, 7, 0)]),
    "me lembra toda terça a quinta às 18 de estudar": ("estudar", [(13, 10, 18, 0), (14, 10, 18, 0), (15, 10, 18, 0)]),
    "me lembra toda segunda, terça, quarta, quinta e sexta às 7 de treinar": ("treinar", [(12, 10, 7, 0), (13, 10, 7, 0), (14, 10, 7, 0), (15, 10, 7, 0), (16, 10, 7, 0)]),
    "me lembra todo domingo, segunda, terça, quarta, quinta, sexta e sábado às 8 de tomar vitamina": ("tomar vitamina", [(18, 10, 8, 0), (12, 10, 8, 0), (13, 10, 8, 0), (14, 10, 8, 0), (15, 10, 8, 0), (16, 10, 8, 0), (17, 10, 8, 0)]),
    "me lembra toda segunda, quarta e sexta às 18h de estudar": ("estudar", [(12, 10, 18, 0), (14, 10, 18, 0), (16, 10, 18, 0)]),
}


def plan(sentence):
    raw = parse_reminder_request(sentence)
    assert raw is not None, sentence
    return plan_reminder(raw, NOW, 9)


class PhraseCorpusTest(unittest.TestCase):
    def test_planned(self):
        for sentence, (text, day, month, hour, minute, repeat) in PLANNED.items():
            with self.subTest(sentence):
                got = plan(sentence)
                self.assertIsInstance(got, Planned, got)
                self.assertEqual(got.text, text)
                self.assertEqual((got.due.day, got.due.month, got.due.hour, got.due.minute), (day, month, hour, minute))
                self.assertEqual(got.repeat, repeat)

    def test_several_weekdays_make_one_weekly_reminder_each(self):
        for sentence, (text, days) in SERIES.items():
            with self.subTest(sentence):
                got = plan(sentence)
                self.assertIsInstance(got, PlannedSeries, got)
                self.assertEqual([(i.due.day, i.due.month, i.due.hour, i.due.minute) for i in got.items], days)
                self.assertTrue(all(i.text == text and i.repeat == "weekly" for i in got.items))

    def test_asks_instead_of_guessing(self):
        for sentence, kind in ASKED.items():
            with self.subTest(sentence):
                got = plan(sentence)
                self.assertIsInstance(got, Ask, got)
                self.assertEqual(got.kind, kind)

    def test_part_of_day_says_the_hour_was_assumed(self):
        self.assertTrue(plan("me lembra amanhã de tarde de buscar o bolo").hour_assumed)
        self.assertFalse(plan("me lembra amanhã às 15 de buscar o bolo").hour_assumed)


if __name__ == "__main__":
    unittest.main()


class SeriesConfirmationTest(unittest.TestCase):
    def test_one_message_lists_every_number_and_day(self):
        from jarvis.reminder_text import series_confirmation
        from jarvis.reminders import Reminder, PENDING

        mon, wed = datetime(2026, 10, 12, 7, 0, tzinfo=TZ), datetime(2026, 10, 14, 7, 0, tzinfo=TZ)
        items = [Reminder(19, "treinar", mon, PENDING, NOW, repeat="weekly"),
                 Reminder(20, "treinar", wed, PENDING, NOW, repeat="weekly")]
        text = series_confirmation(items, NOW)
        self.assertIn("lembretes 19 e 20", text)
        self.assertIn("toda segunda-feira e toda quarta-feira às 07:00", text)
        self.assertNotIn("assumi", text)
        self.assertIn("assumi 07:00", series_confirmation(items, NOW, hour_assumed=True))
