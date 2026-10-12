"""A wide battery for reminders in natural Portuguese. The rules these tests protect:

* an hour is never assumed: no hour -> ask; only "de manhã/de tarde/à noite" -> ask which hour;
* a doubtful hour ("às 3": morning or afternoon?) -> ask;
* a one-off reminder that reads like a routine ("tomar remédio") -> ask if it should repeat;
* the code never marks something it did not understand in full: it asks instead.

Cases are written as tables and multiplied by sentence shape, so one new row covers many phrasings.
"""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.commands import is_yes, parse_reminder_request
from jarvis.reminder_flow import CANCELLED, Dropped, ReminderFlow, hour_answer, strip_filler
from jarvis.reminder_request import Planned, PlannedSeries, is_schedule, plan_from_words, plan_reminder
from jarvis.when import Ask

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 12, 10, 0, tzinfo=TZ)  # segunda-feira, 10:00
CAL = {"seg": 12, "ter": 13, "qua": 14, "qui": 15, "sex": 16, "sab": 17, "dom": 18}  # days of October 2026


def plan(sentence):
    """What the bot does with a typed sentence: the "me lembra" shortcut strips its opening."""
    raw = parse_reminder_request(sentence)
    return plan_reminder(sentence if raw is None else raw, NOW, None)


def shapes(when, text="ligar pro Carlos"):
    """The same request in the shapes people really use."""
    return [
        f"me lembra {when} de {text}",
        f"me lembra de {text} {when}",
        f"me lembra de {text}, {when}",
        f"pode me lembrar {when} de {text}",
        f"Jarvis, me lembra de {text} {when}",
        f"me lembra {when} {text}",
        f"Me lembra de {text} {when}?",
    ]


def due_of(result):
    return (result.due.month, result.due.day, result.due.hour, result.due.minute)


class ExactTimeTest(unittest.TestCase):
    """A day (or none) plus an exact hour: it is marked, in every shape of the sentence."""

    CASES = {
        # day + hour spoken in many ways -> (month, day, hour, minute)
        "amanhã às 9": (10, 13, 9, 0), "amanhã as 9": (10, 13, 9, 0), "amanhã 9h": (10, 13, 9, 0),
        "amanhã às 9h": (10, 13, 9, 0), "amanhã 9:00": (10, 13, 9, 0), "amanhã às 09:00": (10, 13, 9, 0),
        "amanhã 9h00": (10, 13, 9, 0), "amanhã às nove": (10, 13, 9, 0), "amanhã 9h30": (10, 13, 9, 30),
        "amanhã às 9:30": (10, 13, 9, 30), "amanhã às nove e meia": (10, 13, 9, 30),
        "amanhã às 9 e meia": (10, 13, 9, 30), "amanhã às dez e quinze": (10, 13, 10, 15),
        "amanhã às 9 da manhã": (10, 13, 9, 0), "amanhã às nove da manhã": (10, 13, 9, 0),
        "amanhã às 8 e meia da manhã": (10, 13, 8, 30),
        "amanhã às 3 da tarde": (10, 13, 15, 0), "amanhã às três da tarde": (10, 13, 15, 0),
        "amanhã 3 da tarde": (10, 13, 15, 0), "amanhã às duas e meia da tarde": (10, 13, 14, 30),
        "amanhã 15h": (10, 13, 15, 0), "amanhã às 15:30": (10, 13, 15, 30), "amanhã às 20h": (10, 13, 20, 0),
        "amanhã às 8 da noite": (10, 13, 20, 0), "amanhã às oito da noite": (10, 13, 20, 0),
        "amanhã às 8 e meia da noite": (10, 13, 20, 30), "amanhã às 11 da noite": (10, 13, 23, 0),
        "amanhã às 7": (10, 13, 7, 0), "amanhã às 11": (10, 13, 11, 0), "amanhã às 12": (10, 13, 12, 0),
        "amanhã ao meio dia": (10, 13, 12, 0), "amanhã meio dia": (10, 13, 12, 0), "amanhã ao meio-dia": (10, 13, 12, 0),
        "amanhã meia noite": (10, 13, 0, 0), "amanhã às 13h": (10, 13, 13, 0), "amanhã às 23:59": (10, 13, 23, 59),
        # days
        "hoje às 15": (10, 12, 15, 0), "hoje às 3 da tarde": (10, 12, 15, 0), "hoje às 22h": (10, 12, 22, 0),
        "hoje às 10:30": (10, 12, 10, 30), "hoje às 5": (10, 12, 17, 0), "hoje às 3": (10, 12, 15, 0),
        "depois de amanhã às 9": (10, 14, 9, 0), "depois de amanhã às 14h": (10, 14, 14, 0),
        "terça às 9": (10, 13, 9, 0), "terça-feira às 9": (10, 13, 9, 0), "na terça às 9": (10, 13, 9, 0),
        "quarta às 14h": (10, 14, 14, 0), "quinta 8h": (10, 15, 8, 0), "sexta às 15": (10, 16, 15, 0),
        "sexta-feira às 17:30": (10, 16, 17, 30), "sábado às 10": (10, 17, 10, 0), "domingo às 20h": (10, 18, 20, 0),
        "sexta que vem às 9": (10, 16, 9, 0), "sábado que vem às 9": (10, 17, 9, 0),
        "segunda às 15": (10, 12, 15, 0), "segunda às 9": (10, 19, 9, 0), "segunda-feira às 8h": (10, 19, 8, 0),
        "dia 20 às 9": (10, 20, 9, 0), "dia 20 às 14h30": (10, 20, 14, 30), "no dia 20 às 9": (10, 20, 9, 0),
        "dia 20 de novembro às 9": (11, 20, 9, 0), "dia 5 de dezembro às 18h": (12, 5, 18, 0),
        "20/10 às 9": (10, 20, 9, 0), "20/11 às 9": (11, 20, 9, 0), "20/11/2026 às 14:30": (11, 20, 14, 30),
        "2026-11-20 14:30": (11, 20, 14, 30), "dia 12 às 15": (10, 12, 15, 0), "dia 12 às 9": None,
        # no day at all, an exact hour: the next time it happens
        "às 15": (10, 12, 15, 0), "às 15:30": (10, 12, 15, 30), "às 14h": (10, 12, 14, 0),
        "às 8 da manhã": (10, 13, 8, 0), "às 9 da manhã": (10, 13, 9, 0), "às 18 horas": (10, 12, 18, 0),
        # relative
        "daqui a 30 minutos": (10, 12, 10, 30), "daqui a 30 min": (10, 12, 10, 30), "em 45 minutos": (10, 12, 10, 45),
        "em 45 min": (10, 12, 10, 45), "daqui 15 min": (10, 12, 10, 15), "daqui a 2 horas": (10, 12, 12, 0),
        "daqui a duas horas": (10, 12, 12, 0), "em 2 horas": (10, 12, 12, 0), "em meia hora": (10, 12, 10, 30),
        "daqui a meia hora": (10, 12, 10, 30), "daqui a uma hora": (10, 12, 11, 0), "em 1 hora": (10, 12, 11, 0),
        "em 1 hora e meia": (10, 12, 11, 30), "em uma hora e meia": (10, 12, 11, 30),
        "daqui a duas horas e meia": (10, 12, 12, 30), "daqui a 1h": (10, 12, 11, 0),
        "daqui a 3 dias": (10, 15, 10, 0), "daqui a 2 semanas": (10, 26, 10, 0), "em 10 minutos": (10, 12, 10, 10),
    }

    def test_every_case_in_every_shape(self):
        for when, expected in self.CASES.items():
            if expected is None:  # a day that is today, at an hour that already went by: asked, not moved to next month
                self.assertEqual(plan(f"me lembra de ligar pro Carlos {when}").kind, "passou", when)
                continue
            for sentence in shapes(when):
                with self.subTest(sentence):
                    got = plan(sentence)
                    self.assertIsInstance(got, Planned, f"{sentence!r} -> {got}")
                    self.assertEqual(got.text, "ligar pro Carlos", sentence)
                    self.assertEqual(due_of(got), expected, sentence)
                    self.assertIsNone(got.repeat, sentence)

    def test_text_comes_out_clean(self):
        texts = ["ligar pro Carlos", "pagar o aluguel", "buscar o bolo", "enviar o relatório", "comprar pão e leite",
                 "reunião com o time", "buscar a Ana na escola", "levar o carro na oficina"]
        for text in texts:
            for sentence in shapes("amanhã às 9", text):
                with self.subTest(sentence):
                    got = plan(sentence)
                    self.assertIsInstance(got, Planned, f"{sentence!r} -> {got}")
                    self.assertEqual(got.text, text, sentence)

    def test_openings_of_the_request(self):
        for opening in ("me lembra de", "me lembre de", "pode me lembrar de", "poderia me lembrar de", "lembra-me de",
                        "Jarvis, me lembra de", "pode lembrar de", "lembra eu de", "me lembra"):
            sentence = f"{opening} ligar pro Carlos amanhã às 9"
            with self.subTest(sentence):
                self.assertIsNotNone(parse_reminder_request(sentence))
                got = plan(sentence)
                self.assertIsInstance(got, Planned, f"{sentence!r} -> {got}")
                self.assertEqual((got.text, due_of(got)), ("ligar pro Carlos", (10, 13, 9, 0)), sentence)

    def test_advance_warning(self):
        cases = {"10 min antes": 10, "10 minutos antes": 10, "meia hora antes": 30, "1 hora antes": 60,
                 "uma hora antes": 60, "uns 15 minutos antes": 15, "2 horas antes": 120, "10min antes": 10}
        for lead, minutes in cases.items():
            sentence = f"me lembra amanhã às 15 da reunião, {lead}"
            with self.subTest(sentence):
                got = plan(sentence)
                self.assertIsInstance(got, Planned, f"{sentence!r} -> {got}")
                self.assertEqual(got.lead_minutes, minutes)
                self.assertEqual((got.event.hour, got.event.minute), (15, 0))
                self.assertEqual((got.due.hour * 60 + got.due.minute), 15 * 60 - minutes)
        self.assertIsInstance(plan("me lembra amanhã às 9 da reunião, 3 dias antes"), Ask)


class AskTheHourTest(unittest.TestCase):
    """No hour, or a part of the day only, or a doubtful hour: the bot asks and never assumes."""

    NO_HOUR = ["amanhã", "hoje", "depois de amanhã", "sexta", "sexta-feira", "sábado", "domingo", "segunda que vem",
               "dia 20", "dia 20 de novembro", "20/11", "20/10/2026", "na terça", "quinta"]
    PERIOD_ONLY = {
        "amanhã de manhã": "manhã", "amanhã de tarde": "tarde", "amanhã à tarde": "tarde", "hoje à noite": "noite",
        "hoje de noite": "noite", "sexta à noite": "noite", "amanhã cedo": "", "depois de amanhã de manhã": "manhã",
        "de manhã": "manhã", "à noite": "noite", "de tarde": "tarde", "amanhã de madrugada": "madrugada",
        "sábado de manhã": "manhã", "dia 20 à tarde": "tarde", "na segunda de manhã": "manhã", "domingo à noite": "noite",
        "amanhã pela manhã": "manhã", "hoje à tarde": "tarde",
    }
    DOUBTFUL = ["às 8", "às 9", "às 10", "às 9h", "às oito", "amanhã às 3", "sexta às 5", "amanhã 2h", "dia 20 às 4", "amanhã às 1", "sábado às 6", "amanhã às três",
                "quinta às quatro", "amanhã às 6h"]

    def asked(self, sentence):
        got = plan(sentence)
        self.assertIsInstance(got, Ask, f"{sentence!r} -> {got}")
        return got

    def test_no_hour_asks_the_hour(self):
        for when in self.NO_HOUR:
            for sentence in shapes(when):
                with self.subTest(sentence):
                    self.assertEqual(self.asked(sentence).kind, "hora")

    def test_part_of_the_day_asks_which_hour(self):
        for when, period in self.PERIOD_ONLY.items():
            for sentence in shapes(when):
                with self.subTest(sentence):
                    got = self.asked(sentence)
                    self.assertEqual(got.kind, "hora")
                    self.assertIn("Que horas", got.question)
                    if period:
                        self.assertIn(period, got.question)

    def test_doubtful_small_hour_asks_morning_or_afternoon(self):
        for when in self.DOUBTFUL:
            for sentence in shapes(when):
                with self.subTest(sentence):
                    self.assertEqual(self.asked(sentence).kind, "ampm")

    def test_no_time_at_all_asks_when(self):
        for sentence in ("me lembra de ligar pro Carlos", "me lembra", "me lembra de pagar a luz",
                         "pode me lembrar de buscar o bolo", "me lembra de comprar pão"):
            with self.subTest(sentence):
                self.assertIn(self.asked(sentence).kind, {"entendi", "texto"})

    def test_a_time_that_already_passed_asks_again(self):
        for sentence in shapes("hoje às 9") + shapes("hoje às 8 da manhã") + shapes("hoje às 10"):
            with self.subTest(sentence):
                self.assertEqual(self.asked(sentence).kind, "passou")

    def test_impossible_dates_and_hours_are_refused(self):
        for when in ("dia 31 de novembro às 9", "30/02 às 9", "amanhã às 25", "amanhã às 9:75", "dia 40 às 9",
                     "32/12 às 9", "em 99999 minutos", "daqui a 500 dias"):
            sentence = f"me lembra de ligar pro Carlos {when}"
            with self.subTest(sentence):
                self.assertEqual(self.asked(sentence).kind, "invalido")

    def test_unknown_expressions_ask_instead_of_guessing(self):
        for when in ("semana que vem", "mês que vem", "no fim do mês", "ontem às 9", "quando eu chegar", "mais tarde",
                     "daqui a pouco", "qualquer dia", "no natal"):
            sentence = f"me lembra de ligar pro Carlos {when}"
            with self.subTest(sentence):
                self.assertIsInstance(plan(sentence), Ask)


class RepeatTest(unittest.TestCase):
    """Repetition: every closed form works, with an hour; the rest asks, never marks half."""

    DAILY = ["todo dia às 20", "todos os dias às 20", "diariamente às 20", "todo dia, às 20h", "toda manhã às 8",
             "todos os dias às 20:00", "todo dia 20h", "toda noite às 9", "todas as noites às 9", "toda tarde às 3",
             "todo dia às 8 da manhã", "todos os dias às oito da manhã", "toda madrugada às 5"]
    WEEKDAYS = ["nos dias úteis às 20", "dias úteis às 20", "todo dia útil às 20", "de segunda a sexta às 20",
                "toda segunda a sexta às 20", "em dias úteis às 20"]
    WEEKLY = {
        "toda segunda às 9": [(19, 9)], "toda segunda-feira às 9": [(19, 9)], "todas as segundas às 9": [(19, 9)],
        "toda segunda às 15": [(12, 15)],
        "toda terça às 9": [(13, 9)], "toda quarta às 9h": [(14, 9)], "toda quinta às 14:30": [(15, 14)],
        "toda sexta às 17": [(16, 17)], "todo sábado às 10": [(17, 10)], "todo domingo às 20h": [(18, 20)],
        "todos os sábados às 10": [(17, 10)], "toda semana na sexta às 17": [(16, 17)],
        "semanalmente na segunda às 8": [(19, 8)], "toda segunda e quarta às 7": [(19, 7), (14, 7)],
        "toda segunda, quarta e sexta às 7": [(19, 7), (14, 7), (16, 7)], "toda terça a quinta às 18": [(13, 18), (14, 18), (15, 18)],
        "todo sábado e domingo às 10": [(17, 10), (18, 10)], "todas as terças e quintas às 14": [(13, 14), (15, 14)],
        "toda terça e sexta às 3 da tarde": [(13, 15), (16, 15)],
        "toda segunda, terça, quarta, quinta, sexta, sábado e domingo às 8": [(19, 8), (13, 8), (14, 8), (15, 8), (16, 8), (17, 8), (18, 8)],
    }
    TEXT = "enviar o relatório"

    def test_daily(self):
        for when in self.DAILY:
            for sentence in shapes(when, self.TEXT):
                with self.subTest(sentence):
                    got = plan(sentence)
                    self.assertIsInstance(got, Planned, f"{sentence!r} -> {got}")
                    self.assertEqual((got.repeat, got.text), ("daily", self.TEXT))

    def test_weekdays(self):
        for when in self.WEEKDAYS:
            for sentence in shapes(when, self.TEXT):
                with self.subTest(sentence):
                    got = plan(sentence)
                    self.assertIsInstance(got, Planned, f"{sentence!r} -> {got}")
                    self.assertEqual((got.repeat, got.text, got.due.hour), ("weekdays", self.TEXT, 20))
                    self.assertLess(got.due.weekday(), 5)

    def test_weekly_one_reminder_per_day(self):
        for when, days in self.WEEKLY.items():
            for sentence in shapes(when, self.TEXT):
                with self.subTest(sentence):
                    got = plan(sentence)
                    items = got.items if isinstance(got, PlannedSeries) else [got]
                    self.assertTrue(all(isinstance(i, Planned) for i in items), f"{sentence!r} -> {got}")
                    self.assertEqual(sorted((i.due.day, i.due.hour) for i in items), sorted(days), sentence)
                    self.assertTrue(all(i.repeat == "weekly" and i.text == self.TEXT for i in items), sentence)

    def test_repeat_without_an_hour_asks_the_hour(self):
        for when in ("todo dia", "todos os dias", "toda segunda", "toda segunda e quarta", "nos dias úteis",
                     "toda noite", "toda manhã", "toda tarde", "toda semana na sexta", "diariamente"):
            for sentence in shapes(when, self.TEXT):
                with self.subTest(sentence):
                    got = plan(sentence)
                    self.assertIsInstance(got, Ask, f"{sentence!r} -> {got}")
                    self.assertEqual(got.kind, "hora")

    def test_repeat_forms_that_do_not_exist_ask(self):
        for when in ("todo mês dia 5 às 9", "todo dia 20 às 9", "mensalmente às 9", "a cada 2 horas", "de 3 em 3 horas",
                     "quinzenalmente às 9", "todo ano em 5 de maio às 9", "toda quinzena às 9", "a cada 15 minutos"):
            for sentence in shapes(when, self.TEXT)[:3]:
                with self.subTest(sentence):
                    got = plan(sentence)
                    self.assertIsInstance(got, Ask, f"{sentence!r} -> {got}")
                    self.assertEqual(got.kind, "repeticao")

    def test_every_week_without_a_day_asks_which_day(self):
        for when in ("toda semana às 9", "semanalmente às 9", "todas as semanas às 9"):
            with self.subTest(when):
                self.assertEqual(plan(f"me lembra {when} de {self.TEXT}").kind, "dia_semana")

    def test_schedule_sentences_need_no_opening(self):
        yes = ["Toda terça e sexta academia as 15", "todo dia às 7 acordar", "todos os dias as 13: Oração",
               "nos dias úteis às 8:30 standup", "toda segunda a sexta às 7 da manhã treinar",
               "toda segunda às 9 reunião com o time", "diariamente às 21h tomar remédio", "todo sábado às 10 feira"]
        no = ["tenho dentista amanhã às 14", "toda terça eu vou à academia", "toda noite eu estudo", "oi, tudo bem?",
              "todo mês dia 5 pagar o cartão às 9", "a cada 2 horas beber água às 8", "o que tenho de tarefa toda semana?",
              "amanhã às 9 reunião", "me lembra todo dia às 8", "toda vez que chove eu fico em casa"]
        for sentence in yes:
            with self.subTest(sentence):
                self.assertTrue(is_schedule(sentence))
        for sentence in no:
            with self.subTest(sentence):
                self.assertFalse(is_schedule(sentence) and parse_reminder_request(sentence) is None)


class RoutineQuestionTest(unittest.TestCase):
    """A one-off reminder about something people repeat: ask whether it should repeat."""

    ROUTINE = ["tomar remédio", "tomar o remédio da pressão", "tomar vitamina", "tomar água", "ir na academia", "treinar",
               "malhar", "correr", "caminhada", "alongar", "estudar inglês", "aula de inglês", "orar", "oração", "rezar o terço",
               "meditar", "yoga", "pilates", "natação", "fisioterapia", "terapia", "escovar os dentes", "acordar", "standup",
               "daily com o time", "tomar o comprimido"]
    ONE_OFF = ["ligar pro Carlos", "buscar o bolo", "enviar o relatório", "comprar pão", "reunião com o cliente",
               "pagar o aluguel", "pagar a conta de água", "pagar o boleto da academia", "pagar a fatura", "buscar a Ana",
               "levar o carro na oficina", "consulta com o dentista", "ver o jogo"]

    def test_routine_text_asks_whether_to_repeat(self):
        for text in self.ROUTINE:
            for sentence in shapes("amanhã às 8", text)[:3]:
                with self.subTest(sentence):
                    got = plan(sentence)
                    self.assertIsInstance(got, Ask, f"{sentence!r} -> {got}")
                    self.assertEqual(got.kind, "repetir")

    def test_one_off_text_is_marked_straight_away(self):
        for text in self.ONE_OFF:
            for sentence in shapes("amanhã às 8", text)[:3]:
                with self.subTest(sentence):
                    got = plan(sentence)
                    self.assertIsInstance(got, Planned, f"{sentence!r} -> {got}")

    def test_saying_once_or_a_repeat_skips_the_question(self):
        for sentence in ("me lembra amanhã às 8 de tomar remédio, só desta vez", "me lembra só hoje às 15 de ir na academia",
                         "me lembra de tomar remédio amanhã às 8 uma vez",
                         "me lembra todo dia às 20 de tomar remédio", "me lembra toda segunda às 8 de treinar",
                         "me lembra nos dias úteis às 20 de ir na academia", "me lembra toda segunda e quarta às 7 de treinar",
                         "me lembra daqui a 10 minutos de tomar o remédio, só dessa vez"):
            with self.subTest(sentence):
                self.assertIsInstance(plan(sentence), (Planned, PlannedSeries))


class FlowTest(unittest.TestCase):
    """The question and its answer, as a conversation. Every sequence starts from a fresh chat."""

    def talk(self, *messages, text=None, when="", lead=0):
        flow = ReminderFlow()
        first = parse_reminder_request(messages[0])
        result = flow.start(1, messages[0] if first is None else first, NOW, text=text, when=when, lead=lead)
        results = [result]
        for message in messages[1:]:
            results.append(flow.answer(1, message, NOW))
        return results, flow

    def planned(self, result, text, month, day, hour, minute, repeat=None):
        self.assertIsInstance(result, Planned, result)
        self.assertEqual((result.text, due_of(result), result.repeat), (text, (month, day, hour, minute), repeat))

    def test_hour_answers(self):
        answers = {"às 8": (8, 0), "8": (8, 0), "8h": (8, 0), "8:30": (8, 30), "8h30": (8, 30), "oito": (8, 0),
                   "oito e meia": (8, 30), "às oito": (8, 0), "pode ser às 8": (8, 0), "sim, às 8": (8, 0),
                   "por volta das 8": (8, 0), "as 8 e meia": (8, 30), "8 e quinze": (8, 15), "9 da manhã": (9, 0),
                   "às 8!": (8, 0), "Às 8.": (8, 0), "8 horas": (8, 0)}
        for answer, (hour, minute) in answers.items():
            with self.subTest(answer):
                results, _ = self.talk("buscar o bolo amanhã", answer)
                self.assertEqual(results[0].kind, "hora")
                self.planned(results[1], "buscar o bolo", 10, 13, hour, minute)

    def test_hour_of_the_morning_afternoon_night(self):
        cases = [("buscar o bolo amanhã de manhã", "8", 8, 0), ("buscar o bolo amanhã de manhã", "8:45", 8, 45),
                 ("buscar o bolo amanhã de tarde", "3", 15, 0), ("buscar o bolo amanhã de tarde", "três e meia", 15, 30),
                 ("buscar o bolo hoje à noite", "9", 21, 0), ("buscar o bolo hoje à noite", "oito e meia", 20, 30),
                 ("buscar o bolo amanhã cedo", "6", 6, 0), ("buscar o bolo amanhã à tarde", "às 4", 16, 0),
                 ("buscar o bolo sexta à noite", "7", 19, 0)]
        for first, answer, hour, minute in cases:
            with self.subTest(first + " / " + answer):
                results, _ = self.talk(first, answer)
                self.assertEqual(results[0].kind, "hora")
                self.assertIsInstance(results[1], Planned, results[1])
                self.assertEqual((results[1].due.hour, results[1].due.minute), (hour, minute))

    def test_morning_or_afternoon_answers(self):
        for answer, hour in (("tarde", 15), ("da tarde", 15), ("de manhã", 3), ("manhã", 3), ("pode ser à tarde", 15)):
            with self.subTest(answer):
                results, _ = self.talk("buscar o bolo amanhã às 3", answer)
                self.assertEqual(results[0].kind, "ampm")
                self.assertIsInstance(results[1], Planned, results[1])
                self.assertEqual(results[1].due.hour, hour)

    def test_when_answers(self):
        for answer, expected in (("amanhã às 9", (10, 13, 9, 0)), ("sexta às 15", (10, 16, 15, 0)),
                                 ("daqui a 2 horas", (10, 12, 12, 0)), ("dia 20 às 8", (10, 20, 8, 0)),
                                 ("hoje às 18h", (10, 12, 18, 0))):
            with self.subTest(answer):
                results, _ = self.talk("me lembra de ligar pro joão", answer)
                self.assertIn(results[0].kind, {"entendi", "texto"})
                self.planned(results[1], "ligar pro joão", *expected)

    def test_day_then_hour(self):
        results, _ = self.talk("ligar pro joão", "amanhã", "10")
        self.assertEqual([r.kind for r in results[:2]], ["entendi", "hora"])
        self.planned(results[2], "ligar pro joão", 10, 13, 10, 0)

    def test_text_then_when(self):
        results, _ = self.talk("amanhã às 9", "ligar pro joão")
        self.assertEqual(results[0].kind, "texto")
        self.planned(results[1], "ligar pro joão", 10, 13, 9, 0)

    def test_a_time_that_passed_is_replaced_not_merged(self):
        results, _ = self.talk("ligar pro joão hoje às 9", "amanhã às 10")
        self.assertEqual(results[0].kind, "passou")
        self.planned(results[1], "ligar pro joão", 10, 13, 10, 0)

    def test_giving_up(self):
        for answer in ("deixa pra lá", "não", "esquece", "cancela", "nada", "melhor não"):
            with self.subTest(answer):
                results, flow = self.talk("ligar pro joão amanhã", answer)
                self.assertEqual(results[1], Dropped(CANCELLED))
                self.assertFalse(flow.pending(1))

    def test_an_unrelated_message_is_not_an_answer(self):
        for message in ("banana", "que horas são?", "o que você pode fazer?", "obrigado", "quais minhas tarefas?"):
            with self.subTest(message):
                results, flow = self.talk("ligar pro joão amanhã", message)
                self.assertIsNone(results[1])
                self.assertFalse(flow.pending(1))  # and it does not keep waiting for a late answer

    def test_a_new_request_replaces_the_old_one(self):
        flow = ReminderFlow()
        flow.start(1, "ligar pro joão amanhã", NOW)
        self.assertIsNone(flow.answer(1, "me lembra de buscar o bolo amanhã às 9", NOW))
        self.assertIsNone(flow.answer(1, "toda terça e sexta academia as 15", NOW))

    def test_an_old_question_expires(self):
        from datetime import timedelta

        flow = ReminderFlow()
        flow.start(1, "ligar pro joão amanhã", NOW)
        self.assertIsNone(flow.answer(1, "às 8", NOW + timedelta(minutes=11)))

    def test_chats_do_not_mix(self):
        flow = ReminderFlow()
        flow.start(1, "ligar pro joão amanhã", NOW)
        flow.start(2, "buscar o bolo sexta", NOW)
        self.planned(flow.answer(2, "15", NOW), "buscar o bolo", 10, 16, 15, 0)
        self.planned(flow.answer(1, "8", NOW), "ligar pro joão", 10, 13, 8, 0)

    def test_repeat_question_and_its_answers(self):
        first = "tomar remédio amanhã às 8"
        cases = {"todo dia": ("daily", [(13, 8)]), "todos os dias": ("daily", [(13, 8)]), "dias úteis": ("weekdays", [(13, 8)]),
                 "nos dias úteis": ("weekdays", [(13, 8)]), "toda segunda": ("weekly", [(19, 8)]),
                 "sim, todo dia": ("daily", [(13, 8)]), "quero todo dia": ("daily", [(13, 8)]), "pode ser todo dia": ("daily", [(13, 8)]),
                 "toda segunda e quarta": ("weekly", [(14, 8), (19, 8)]), "toda terça e quinta": ("weekly", [(13, 8), (15, 8)]),
                 "todo domingo": ("weekly", [(18, 8)])}
        for answer, (repeat, days) in cases.items():
            with self.subTest(answer):
                results, _ = self.talk(first, answer)
                self.assertEqual(results[0].kind, "repetir")
                got = results[1]
                items = got.items if isinstance(got, PlannedSeries) else [got]
                self.assertEqual(sorted((i.due.day, i.due.hour) for i in items), sorted(days), answer)
                self.assertTrue(all(i.repeat == repeat and i.text == "tomar remédio" for i in items), answer)

    def test_repeat_question_once_answers(self):
        for answer in ("só dessa vez", "só desta vez", "não", "só hoje", "uma vez", "apenas uma vez", "não precisa", "sem repetir"):
            with self.subTest(answer):
                results, flow = self.talk("tomar remédio amanhã às 8", answer)
                self.planned(results[1], "tomar remédio", 10, 13, 8, 0)
                self.assertFalse(flow.pending(1))

    def test_bare_yes_asks_how_often(self):
        for yes in ("sim", "quero", "pode", "claro", "isso", "aham", "sim por favor"):
            with self.subTest(yes):
                results, flow = self.talk("tomar remédio amanhã às 8", yes, "todo dia")
                self.assertEqual(results[1].kind, "frequencia")
                self.planned(results[2], "tomar remédio", 10, 13, 8, 0, "daily")

    def test_every_week_asks_which_day_and_gets_it(self):
        results, _ = self.talk("tomar remédio amanhã às 8", "toda semana", "terça")
        self.assertEqual(results[1].kind, "dia_semana")
        self.planned(results[2], "tomar remédio", 10, 13, 8, 0, "weekly")

    def test_repeat_question_is_asked_only_once(self):
        results, flow = self.talk("tomar remédio amanhã às 8", "não")
        self.assertIsInstance(results[1], Planned)
        self.assertIsNone(flow.answer(1, "não", NOW))

    def test_routine_with_missing_hour_asks_hour_then_repeat(self):
        results, _ = self.talk("tomar remédio de manhã", "8", "todo dia")
        self.assertEqual([r.kind for r in results[:2]], ["hora", "repetir"])
        self.planned(results[2], "tomar remédio", 10, 13, 8, 0, "daily")

    def test_repeat_with_missing_hour_then_hour(self):
        results, _ = self.talk("academia todo dia de manhã", "7")
        self.assertEqual(results[0].kind, "hora")
        self.planned(results[1], "academia", 10, 13, 7, 0, "daily")

    def test_unrelated_answer_to_the_repeat_question_creates_nothing(self):
        for message in ("banana", "que horas são?", "amanhã às 9"):
            with self.subTest(message):
                results, flow = self.talk("tomar remédio amanhã às 8", message)
                self.assertIsNone(results[1])


class ModelPathTest(unittest.TestCase):
    """The model chose to create the reminder: it gives the text; the user's own words give the time."""

    def go(self, said, text, when="", lead=0):
        return ReminderFlow().start(1, said, NOW, text=text, when=when, lead=lead)

    def test_model_that_drops_days_and_hour(self):
        got = self.go("Pode lembrar todas as terças e quintas de ir na aula de inglês às duas da tarde?",
                      "ir na aula de inglês", "toda terça")
        self.assertIsInstance(got, PlannedSeries)
        self.assertEqual([(i.due.day, i.due.hour) for i in got.items], [(13, 14), (15, 14)])

    def test_model_that_invents_an_hour_is_not_believed(self):
        for said in ("me avisa amanhã de buscar o bolo", "avisa amanhã do bolo", "pode me avisar sexta da reunião"):
            with self.subTest(said):
                got = self.go(said, "buscar o bolo", "amanhã às 9")
                self.assertIsInstance(got, Ask, got)
                self.assertEqual(got.kind, "hora")

    def test_model_that_invents_a_period_hour_is_not_believed(self):
        got = self.go("me avisa amanhã à tarde do bolo", "buscar o bolo", "amanhã às 15")
        self.assertEqual(got.kind, "hora")

    def test_hour_question_then_answer_keeps_the_models_text(self):
        flow = ReminderFlow()
        self.assertEqual(flow.start(1, "me avisa amanhã do bolo", NOW, text="buscar o bolo", when="amanhã").kind, "hora")
        got = flow.answer(1, "às 10", NOW)
        self.assertEqual((got.text, due_of(got)), ("buscar o bolo", (10, 13, 10, 0)))

    def test_words_without_a_time_fall_back_to_the_model(self):
        # the user only said "yes" to an offer: the model's `quando` is the request
        got = self.go("amanhã às 9", "pagar a luz", "amanhã às 9")
        self.assertEqual((got.text, due_of(got)), ("pagar a luz", (10, 13, 9, 0)))
        got = self.go("quero sim", "ligar pro Carlos", "amanhã às 9")
        self.assertEqual((got.text, due_of(got)), ("ligar pro Carlos", (10, 13, 9, 0)))

    def test_model_hint_without_an_hour_asks_it(self):
        got = self.go("sim", "ligar pro Carlos", "amanhã")
        self.assertEqual(got.kind, "hora")

    def test_model_text_that_is_a_routine_asks_to_repeat(self):
        got = self.go("me avisa amanhã às 8 do remédio", "tomar remédio", "amanhã às 8")
        self.assertEqual(got.kind, "repetir")

    def test_advance_warning_survives(self):
        got = self.go("me avisa amanhã às 15 da reunião, 10 min antes", "reunião", "amanhã às 15", 10)
        self.assertIsInstance(got, Planned)
        self.assertEqual((got.lead_minutes, got.event.hour, got.due.minute), (10, 15, 50))

    def test_direct_plan_helper_matches_the_flow(self):
        got = plan_from_words("me avisa amanhã às 9 da prova", "prova", "amanhã", 0, NOW, None)
        self.assertEqual((got.text, due_of(got)), ("prova", (10, 13, 9, 0)))


class AnswerShapingTest(unittest.TestCase):
    def test_hour_answer(self):
        cases = {"8": "as 8", "8h": "as 8", "8:30": "as 8:30", "8h30": "as 8:30", "às 8": "as 8", "oito": "as oito",
                 "oito e meia": "as oito e meia", "3 da tarde": "as 3 da tarde", "meio dia": "meio dia",
                 "amanhã às 9": "amanhã às 9", "tarde": "tarde", "banana": "banana", "pode ser 8": "as 8",
                 "8 e quinze": "as 8 e quinze", "por volta das 8": "as 8"}
        for answer, expected in cases.items():
            with self.subTest(answer):
                self.assertEqual(hour_answer(answer), expected)

    def test_strip_filler(self):
        self.assertEqual(strip_filler("sim, pode ser às 8"), "às 8")
        self.assertEqual(strip_filler("quero todo dia"), "todo dia")
        self.assertEqual(strip_filler("às 8"), "às 8")
        self.assertEqual(strip_filler("sim"), "sim")

    def test_bare_yes(self):
        for text in ("sim", "pode", "quero", "claro"):
            self.assertTrue(is_yes(text))
        for text in ("todo dia", "às 8", "não"):
            self.assertFalse(is_yes(text))


if __name__ == "__main__":
    unittest.main()


class CombinatorialTest(unittest.TestCase):
    """Thousands of generated requests: every day form x every hour form x many texts x every sentence shape.
    The expected date and hour are computed from the parts, so a failure points at a real gap, not at a typo."""

    DAYS = [("hoje", 0), ("amanhã", 1), ("depois de amanhã", 2), ("terça", 1), ("quarta", 2), ("quinta", 3),
            ("sexta", 4), ("sábado", 5), ("domingo", 6), ("na sexta", 4), ("sexta-feira", 4), ("dia 20", 8),
            ("20/10", 8), ("dia 25 de outubro", 13), ("dia 3 de novembro", 22), ("25/12", 74)]
    HOURS = [("às 15", 15, 0), ("15h", 15, 0), ("15:30", 15, 30), ("às 3 da tarde", 15, 0), ("às três da tarde", 15, 0),
             ("às 8 da noite", 20, 0), ("às oito e meia da noite", 20, 30), ("às 14h30", 14, 30), ("ao meio dia", 12, 0),
             ("meio-dia", 12, 0), ("às 9 da manhã", 9, 0), ("às nove da manhã", 9, 0), ("às 11", 11, 0), ("às 18:45", 18, 45),
             ("às 7 da manhã", 7, 0), ("às 10 e meia da noite", 22, 30), ("às 23h", 23, 0), ("às 16", 16, 0)]
    TEXTS = ["ligar pro Carlos", "buscar o bolo", "enviar o relatório", "comprar 2 pães", "falar com a tia Maria",
             "ver o jogo", "reunião com o time", "levar o carro na oficina", "pegar o Pedro na escola",
             "imprimir os documentos", "renovar a carteira", "buscar a encomenda", "ligar pro banco"]

    def test_all_combinations(self):
        from datetime import timedelta

        failures = []
        count = 0
        for day, offset in self.DAYS:
            date = (NOW + timedelta(days=offset)).date()
            for hour_words, hour, minute in self.HOURS:
                if offset == 0 and (hour, minute) <= (10, 0):
                    continue  # today, already past: asked, covered elsewhere
                for text in self.TEXTS:
                    for sentence in shapes(f"{day} {hour_words}", text):
                        count += 1
                        got = plan(sentence)
                        want = (date.month, date.day, hour, minute)
                        if not isinstance(got, Planned) or got.text != text or due_of(got) != want or got.repeat:
                            failures.append(f"{sentence!r} -> {got if not isinstance(got, Planned) else (got.text, due_of(got))}, wanted {(text, want)}")
        self.assertGreater(count, 3000)
        self.assertEqual(failures, [], f"{len(failures)} of {count} failed, first ones:\n" + "\n".join(failures[:15]))

    def test_every_hour_form_with_an_exact_hour_and_a_period_word_agrees(self):
        """"às 3 da tarde" and "15h" and "três da tarde" mean the same thing."""
        spoken = ["às 3 da tarde", "às três da tarde", "3 da tarde", "15h", "15:00", "às 15", "às 15h"]
        results = {when: due_of(plan(f"me lembra amanhã {when} de ligar pro Carlos")) for when in spoken}
        self.assertEqual(set(results.values()), {(10, 13, 15, 0)}, results)


class HardSentencesTest(unittest.TestCase):
    """Sentences written on purpose to break the parser. Each one went wrong before it was fixed."""

    OK = {
        "me lembra ligar amanhã pro Carlos às 9": ("ligar pro Carlos", (10, 13, 9, 0)),
        "me lembra de reunião de tarde com o time amanhã às 15": ("reunião de tarde com o time", (10, 13, 15, 0)),
        "me lembra de ver o jogo de domingo às 16": ("ver o jogo", (10, 18, 16, 0)),
        "me lembra de ligar pro 190 amanhã às 9": ("ligar pro 190", (10, 13, 9, 0)),
        "me lembra do apartamento 12 amanhã às 9": ("apartamento 12", (10, 13, 9, 0)),
        "me lembra de pagar 2 boletos amanhã às 9": ("pagar 2 boletos", (10, 13, 9, 0)),
        "me lembra de ligar 3 vezes amanhã às 9": ("ligar 3 vezes", (10, 13, 9, 0)),
        "ME LEMBRA AMANHÃ ÀS 9 DE LIGAR PRO CARLOS": ("LIGAR PRO CARLOS", (10, 13, 9, 0)),
        "me lembra   amanhã   às  9   de ligar": ("ligar", (10, 13, 9, 0)),
        "me lembra amanha as 9 de ligar pro carlos": ("ligar pro carlos", (10, 13, 9, 0)),
        "me lembra sexta feira às 9 de ligar": ("ligar", (10, 16, 9, 0)),
        "me lembra amanhã às 9 horas de ligar": ("ligar", (10, 13, 9, 0)),
        "me lembra amanhã às 9hrs de ligar": ("ligar", (10, 13, 9, 0)),
        "me lembra amanhã 9 horas da manhã de ligar": ("ligar", (10, 13, 9, 0)),
        "me lembra amanhã de manhã às 9 de ligar": ("ligar", (10, 13, 9, 0)),
        "me lembra amanhã à noite às 9 de ligar": ("ligar", (10, 13, 21, 0)),
        "me lembra hoje à tarde às 4 de ligar": ("ligar", (10, 12, 16, 0)),
        "me lembra daqui a 1h30 de ver o bolo": ("ver o bolo", (10, 12, 11, 30)),
        "me lembra daqui a 90 minutos de ver o bolo": ("ver o bolo", (10, 12, 11, 30)),
        "me lembra daqui a vinte e cinco minutos de ver o bolo": ("ver o bolo", (10, 12, 10, 25)),
        "me lembra em quarenta e cinco minutos de ver o bolo": ("ver o bolo", (10, 12, 10, 45)),
        "me lembra daqui a vinte minutos de ver o bolo": ("ver o bolo", (10, 12, 10, 20)),
        "me lembra daqui a um minuto de ver o bolo": ("ver o bolo", (10, 12, 10, 1)),
        "me lembra amanhã ao meio dia e meia de ligar": ("ligar", (10, 13, 12, 30)),
        "me lembra hoje à meia noite de ligar": ("ligar", (10, 13, 0, 0)),
        "me lembra amanhã às 00:30 de ligar": ("ligar", (10, 13, 0, 30)),
        "me lembra dia primeiro às 9 de ligar": ("ligar", (11, 1, 9, 0)),
        "me lembra 20 de novembro às 9 de ligar": ("ligar", (11, 20, 9, 0)),
        "me lembra no dia 20 do 11 às 9 de ligar": ("ligar", (11, 20, 9, 0)),
        "me lembra dia 5 de dezembro de 2026 às 9 de ligar": ("ligar", (12, 5, 9, 0)),
        "me lembra sexta da semana que vem às 9 de ligar": ("ligar", (10, 23, 9, 0)),
        "me lembra na segunda da próxima semana às 9 de ligar": ("ligar", (10, 19, 9, 0)),
        "me lembra no próximo domingo às 9 de ligar": ("ligar", (10, 18, 9, 0)),
        "me lembra hoje mais tarde às 18 de ligar": ("ligar", (10, 12, 18, 0)),
        "me lembra aí que amanhã tenho dentista às 9": ("tenho dentista", (10, 13, 9, 0)),
        "me lembra que tenho dentista amanhã às 9": ("tenho dentista", (10, 13, 9, 0)),
        "me lembra quinta-feira que vem às 14h de ligar": ("ligar", (10, 15, 14, 0)),
        "me lembra de ir às 3 da tarde amanhã": ("ir", (10, 13, 15, 0)),
        "me lembra às 3 da tarde de amanhã de ligar": ("ligar", (10, 13, 15, 0)),
        "me lembra amanhã às 19:00h de ligar": ("ligar", (10, 13, 19, 0)),
        "me lembra amanhã às 19h00 de ligar": ("ligar", (10, 13, 19, 0)),
        "me lembra amanhã à uma da tarde de ligar": ("ligar", (10, 13, 13, 0)),
        "me lembra amanhã às 13 horas de ligar": ("ligar", (10, 13, 13, 0)),
    }
    ASK = {
        "me lembra de buscar o Pedro às 5": "ampm",
        "me lembra amanhã às 9 e às 15 de ligar": "varios",
        "me lembra amanhã às 9 ou 10 de ligar": "varios",
        "me lembra de ligar pro Carlos amanhã às 9 e pro Pedro às 10": "varios",
        "me lembra das 8 às 10 de ligar": "varios",
        "me lembra em 5 minutos": "texto",
        "me lembra às 24h de ligar": "invalido",
        "me lembra na próxima semana de ligar": "entendi",
        "me lembra daqui a 30 segundos de ver o bolo": "entendi",
        "me lembra mês que vem às 9 de ligar": "entendi",
        "me lembra no natal às 9 de ligar": "entendi",
        "me lembra de ligar pro Carlos amanhã às 9 da manhã e às 8 da noite": "varios",
    }

    def test_sentences_that_must_be_understood(self):
        for sentence, (text, due) in self.OK.items():
            with self.subTest(sentence):
                got = plan(sentence)
                self.assertIsInstance(got, Planned, f"{sentence!r} -> {got}")
                self.assertEqual((got.text, due_of(got)), (text, due), sentence)

    def test_sentences_that_must_be_asked(self):
        for sentence, kind in self.ASK.items():
            with self.subTest(sentence):
                got = plan(sentence)
                self.assertIsInstance(got, Ask, f"{sentence!r} -> {got}")
                self.assertEqual(got.kind, kind, sentence)

    def test_the_lembra_command_without_an_opening(self):
        for when, expected in ExactTimeTest.CASES.items():
            if expected is None:
                continue
            for sentence in (f"{when} ligar pro Carlos", f"ligar pro Carlos {when}"):
                with self.subTest(sentence):
                    got = plan_reminder(sentence, NOW, None)
                    self.assertIsInstance(got, Planned, f"{sentence!r} -> {got}")
                    self.assertEqual((got.text, due_of(got)), ("ligar pro Carlos", expected), sentence)
