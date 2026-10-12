"""Regression corpus: real-sounding "me lembra ..." sentences and what each must become.
Each sentence that went wrong on the phone is added here with the right answer."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.commands import parse_reminder_request
from jarvis.reminder_request import Planned, PlannedSeries, is_schedule, plan_from_words, plan_reminder
from jarvis.when import Ask

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 11, 15, 0, tzinfo=TZ)  # domingo

# sentence -> (text, day, month, hour, minute, repeat)
PLANNED = {
    "me lembra em 1 hora e meia de ver o bolo": ("ver o bolo", 11, 10, 16, 30, None),
    "me lembra daqui a duas horas e meia de ver o bolo": ("ver o bolo", 11, 10, 17, 30, None),
    "me lembra às nove da noite de fechar o caixa": ("fechar o caixa", 11, 10, 21, 0, None),
    "me lembra de orar todo dia ao meio dia": ("orar", 12, 10, 12, 0, "daily"),
    "me lembra todos os dias as 13: Oração": ("Oração", 12, 10, 13, 0, "daily"),
    "me lembra na sexta que vou ao médico às 14h": ("vou ao médico", 16, 10, 14, 0, None),
    "me lembra sábado que vem de comprar presente": ("comprar presente", 17, 10, 9, 0, None),
    "me lembra às 8:30 da manhã de amanhã de buscar o pacote": ("buscar o pacote", 12, 10, 8, 30, None),
    "me lembra toda segunda a sexta às 7 da manhã de treinar": ("treinar", 12, 10, 7, 0, "weekdays"),
    "me lembra do dentista amanhã às 14": ("dentista", 12, 10, 14, 0, None),
    # as the audio transcription writes them: question mark at the end, "uma", "à tarde", "às sete da manhã"
    "Me lembra em uma hora e meia de ver o bolo?": ("ver o bolo", 11, 10, 16, 30, None),
}
# sentence -> the kind of question the code must ask instead of guessing
ASKED = {
    # a part of the day without an hour is never turned into one: the code asks which hour
    "me lembra de ligar pro joão amanhã de manhã": "hora",
    "me lembra amanhã cedo de pagar a luz": "hora",
    "me lembra amanhã de tarde de buscar o bolo": "hora",
    "me lembra hoje à noite de ligar pra minha mãe": "hora",
    "me lembra de manhã de buscar o pacote": "hora",
    "Me lembra amanhã à tarde de buscar o bolo?": "hora",
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


class ModelDroppedDetailsTest(unittest.TestCase):
    """What the Groq model really sent on the phone: it kept the text but lost days and hours."""

    def test_days_and_hour_come_from_the_users_words(self):
        said = "Pode lembrar todas as terças e quintas de ir na aula de inglês às duas da tarde?"
        got = plan_from_words(said, "ir na aula de inglês", "toda terça", 0, NOW, 9)
        self.assertIsInstance(got, PlannedSeries)
        self.assertEqual([(i.due.day, i.due.hour) for i in got.items], [(13, 14), (15, 14)])
        self.assertTrue(all(i.text == "ir na aula de inglês" and i.repeat == "weekly" for i in got.items))

    def test_single_reminder_keeps_the_models_text_and_the_users_time(self):
        got = plan_from_words("me avisa amanhã às 7 que tem prova", "prova", "amanhã", 0, NOW, 9)
        self.assertIsInstance(got, Planned)
        self.assertEqual((got.text, got.due.day, got.due.hour), ("prova", 12, 7))

    def test_falls_back_to_the_model_when_the_users_words_have_no_time(self):
        got = plan_from_words("anota aí pra me avisar disso", "pagar a luz", "amanhã às 9", 0, NOW, 9)
        self.assertIsInstance(got, Planned)
        self.assertEqual((got.text, got.due.day, got.due.hour), ("pagar a luz", 12, 9))

    def test_a_question_about_the_users_time_is_relayed(self):
        got = plan_from_words("me lembra amanhã de buscar o bolo", "buscar o bolo", "amanhã às 9", 0, NOW, None)
        self.assertIsInstance(got, Ask)
        self.assertEqual(got.kind, "hora")


class ScheduleSentenceTest(unittest.TestCase):
    def test_repeat_plus_an_exact_hour_is_a_reminder(self):
        for sentence in ("Toda terça e sexta academia as 15", "todo dia às 7 acordar", "todos os dias as 13: Oração",
                         "nos dias úteis às 8:30 standup", "toda segunda a sexta às 7 da manhã treinar",
                         "Toda terça e sexta academia às três da tarde"):
            with self.subTest(sentence):
                self.assertTrue(is_schedule(sentence))

    def test_anything_less_is_left_to_the_model(self):
        for sentence in ("tenho dentista amanhã às 14", "toda terça eu vou à academia", "toda noite eu estudo",
                         "todo mês dia 5 pagar o cartão às 9", "a cada 2 horas beber água às 8", "oi, tudo bem?",
                         "o que tenho de tarefa toda semana?"):
            with self.subTest(sentence):
                self.assertFalse(is_schedule(sentence))

    def test_the_sentence_becomes_one_reminder_per_day(self):
        got = plan_reminder("Toda terça e sexta academia as 15", NOW, 9)
        self.assertIsInstance(got, PlannedSeries)
        self.assertEqual([(i.due.day, i.due.hour, i.text) for i in got.items], [(13, 15, "academia"), (16, 15, "academia")])
