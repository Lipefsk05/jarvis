import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.when import Ask, When, describe, parse

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 9, 11, 0, tzinfo=TZ)  # sexta-feira


def at(day, month, hour, minute=0, year=2026):
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


class RelativeTest(unittest.TestCase):
    def test_minutes_hours_days(self):
        cases = {
            "daqui a 20 minutos": at(9, 10, 11, 20),
            "daqui a 20 min": at(9, 10, 11, 20),
            "em 2 horas": at(9, 10, 13, 0),
            "daqui duas horas": at(9, 10, 13, 0),
            "daqui a uma hora": at(9, 10, 12, 0),
            "daqui a meia hora": at(9, 10, 11, 30),
            "em 3 dias": at(12, 10, 11, 0),
            "daqui a 1 semana": at(16, 10, 11, 0),
            "daqui a 2h": at(9, 10, 13, 0),
        }
        for text, expected in cases.items():
            self.assertEqual(parse(text, NOW), When(expected), text)

    def test_absurd_amounts_are_questioned(self):
        self.assertIsInstance(parse("daqui a 0 minutos", NOW), Ask)
        self.assertIsInstance(parse("daqui a 99999 horas", NOW), Ask)


class DayAndHourTest(unittest.TestCase):
    def test_tomorrow_and_today(self):
        self.assertEqual(parse("amanhã às 9", NOW), When(at(10, 10, 9)))
        self.assertEqual(parse("Amanhã às 9h30", NOW), When(at(10, 10, 9, 30)))
        self.assertEqual(parse("depois de amanhã 14:15", NOW), When(at(11, 10, 14, 15)))
        self.assertEqual(parse("hoje às 15h", NOW), When(at(9, 10, 15)))
        self.assertEqual(parse("amanhã de manhã às 8", NOW), When(at(10, 10, 8)))

    def test_period_words(self):
        self.assertEqual(parse("amanhã 8 da noite", NOW), When(at(10, 10, 20)))
        self.assertEqual(parse("amanhã às 3 da tarde", NOW), When(at(10, 10, 15)))
        self.assertEqual(parse("amanhã meio-dia", NOW), When(at(10, 10, 12)))
        self.assertEqual(parse("amanhã meia-noite", NOW), When(at(10, 10, 0)))

    def test_bare_hour_rolls_to_tomorrow_when_it_passed(self):
        self.assertEqual(parse("às 15h", NOW), When(at(9, 10, 15)))
        self.assertEqual(parse("às 15", NOW), When(at(9, 10, 15)))
        self.assertEqual(parse("às 15h", datetime(2026, 10, 9, 16, 0, tzinfo=TZ)), When(at(10, 10, 15)))
        self.assertEqual(parse("às 9h", NOW).kind, "ampm")  # 09:00 passed, 21:00 ahead: ask, do not guess

    def test_ambiguous_bare_hour_is_questioned(self):
        result = parse("às 8", NOW)  # 08:00 passed today, 20:00 is still ahead
        self.assertEqual(result.kind, "ampm")
        self.assertEqual(parse("às 8 da manhã", NOW), When(at(10, 10, 8)))
        self.assertEqual(parse("às 8 da noite", NOW), When(at(9, 10, 20)))

    def test_weekdays(self):
        self.assertEqual(parse("segunda às 9", NOW), When(at(12, 10, 9)))
        self.assertEqual(parse("quarta-feira 14h", NOW), When(at(14, 10, 14)))
        self.assertEqual(parse("sábado às 10", NOW), When(at(10, 10, 10)))
        self.assertEqual(parse("domingo 18h", NOW), When(at(11, 10, 18)))

    def test_same_weekday_today(self):
        self.assertEqual(parse("sexta às 15h", NOW), When(at(9, 10, 15)))  # still ahead today
        self.assertEqual(parse("sexta às 9h", NOW), When(at(16, 10, 9)))  # passed: next Friday
        self.assertEqual(parse("sexta às 9h", NOW, default_hour=9), When(at(16, 10, 9)))

    def test_explicit_dates(self):
        self.assertEqual(parse("15/10 às 14:30", NOW), When(at(15, 10, 14, 30)))
        self.assertEqual(parse("20/11/2026 9h", NOW), When(at(20, 11, 9)))
        self.assertEqual(parse("dia 20 às 10", NOW), When(at(20, 10, 10)))
        self.assertEqual(parse("dia 5 às 10", NOW), When(at(5, 11, 10)))  # day 5 of this month passed
        self.assertEqual(parse("dia 3 de dezembro às 8h", NOW), When(at(3, 12, 8)))
        self.assertEqual(parse("1/2 às 8h", NOW), When(at(1, 2, 8, year=2027)))  # already past this year
        self.assertEqual(parse("2026-10-12 08:15", NOW), When(at(12, 10, 8, 15)))
        self.assertEqual(parse("2026-10-12T08:15", NOW), When(at(12, 10, 8, 15)))

    def test_invalid_dates_and_hours_are_questioned(self):
        for text in ("31/02 às 9", "dia 40 às 9", "amanhã às 25h", "amanhã às 9:75"):
            result = parse(text, NOW)
            self.assertIsInstance(result, Ask, text)
            self.assertEqual(result.kind, "invalido", text)


class MissingPartsTest(unittest.TestCase):
    def test_day_without_hour_asks_or_uses_default(self):
        ask = parse("amanhã", NOW)
        self.assertEqual(ask.kind, "hora")
        self.assertIn("amanhã", ask.question)
        self.assertEqual(parse("amanhã", NOW, default_hour=9), When(at(10, 10, 9), hour_assumed=True))
        self.assertEqual(parse("segunda", NOW, default_hour=9), When(at(12, 10, 9), hour_assumed=True))
        self.assertFalse(parse("amanhã às 9", NOW, default_hour=7).hour_assumed)

    def test_default_hour_in_the_past_today_is_questioned(self):
        self.assertEqual(parse("hoje", NOW, default_hour=9).kind, "passou")

    def test_past_times_are_questioned(self):
        self.assertEqual(parse("hoje às 8h", NOW).kind, "passou")
        self.assertEqual(parse("2026-10-01 10:00", NOW).kind, "passou")

    def test_not_understood_asks_and_never_guesses(self):
        for text in ("", "   ", "daqui a pouco", "depois do almoço", "quando der", "semana que vem", "blablabla"):
            result = parse(text, NOW)
            self.assertIsInstance(result, Ask, text)
            self.assertEqual(result.kind, "entendi", text)

    def test_naive_now_never_leaks_into_results(self):
        self.assertEqual(parse("amanhã às 9", NOW).dt.tzinfo, TZ)


class DescribeTest(unittest.TestCase):
    def test_reads_back_naturally(self):
        self.assertEqual(describe(at(9, 10, 15), NOW), "hoje às 15:00")
        self.assertEqual(describe(at(10, 10, 9), NOW), "amanhã às 09:00")
        self.assertEqual(describe(at(16, 10, 9, 30), NOW), "sexta-feira, 16/10 às 09:30")
