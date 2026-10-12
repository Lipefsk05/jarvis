"""Clashes between reminders: same minute, overlap (known duration), near (unknown duration, within an hour),
repeating ones, and the conversation around the question "marco mesmo assim?"."""
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from jarvis.conflicts import Slot, clash, find_conflicts, occurrences, question
from jarvis.reminder_flow import CANCELLED, Dropped, ReminderFlow
from jarvis.reminder_request import Planned, PlannedSeries, plan_reminder, take_duration
from jarvis.reminders import PENDING, Reminder
from jarvis.when import Ask

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 12, 8, 0, tzinfo=TZ)  # segunda-feira, 08:00


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


def stored(id, text, when, duration=0, repeat=None):
    return Reminder(id, text, when, PENDING, NOW, repeat=repeat, duration=duration)


class DurationTest(unittest.TestCase):
    def test_how_long_it_lasts(self):
        cases = {
            "treinar às 9 por 2 horas": ("treinar às 9", 120), "treinar às 9 por 90 minutos": ("treinar às 9", 90),
            "treinar às 9 durante 1h30": ("treinar às 9", 90), "treinar às 9 por uma hora e meia": ("treinar às 9", 90),
            "treinar às 9 por meia hora": ("treinar às 9", 30), "treinar às 9 que dura duas horas": ("treinar às 9", 120),
            "treinar às 9 dura 2h": ("treinar às 9", 120), "treinar às 9 por 2 horas e 15 minutos": ("treinar às 9", 135),
        }
        for raw, (rest, minutes) in cases.items():
            with self.subTest(raw):
                got, duration, ask = take_duration(raw)
                self.assertEqual((got, duration, ask), (rest, minutes, None))

    def test_a_range_gives_the_start_and_the_duration(self):
        cases = {
            "das 9 às 11 treinar": ("às 9 treinar", 120), "treinar das 9h às 11h": ("treinar às 9", 120),
            "treinar de 9 às 11 da manhã": ("treinar às 9 da manha", 120), "treinar das 9:30 às 11": ("treinar às 9h30", 90),
            "treinar das 10 às 2": ("treinar às 10", 240), "treinar das 9 até 11": ("treinar às 9", 120),
        }
        for raw, (rest, minutes) in cases.items():
            with self.subTest(raw):
                got, duration, ask = take_duration(raw)
                self.assertEqual((got, duration, ask), (rest, minutes, None))

    def test_not_a_duration(self):
        for raw in ("treinar às 9 por 2", "comprar por 2 reais", "ligar de 3 a 5 pessoas", "treinar às 9"):
            with self.subTest(raw):
                self.assertEqual(take_duration(raw), (raw, 0, None))

    def test_nonsense_is_asked(self):
        for raw in ("treinar das 11 às 9", "treinar das 14 às 12", "treinar às 9 por 30 horas"):
            with self.subTest(raw):
                self.assertEqual(take_duration(raw)[2].kind, "invalido")

    def test_the_planned_reminder_carries_it(self):
        got = plan_reminder("amanhã às 9 treinar por 2 horas", NOW, None, ask_repeat=False)
        self.assertIsInstance(got, Planned)
        self.assertEqual((got.text, got.due, got.duration), ("treinar", at(13, 9), 120))
        got = plan_reminder("toda segunda e quarta das 9 às 11 treinar", NOW, None, ask_repeat=False)
        self.assertIsInstance(got, PlannedSeries)
        self.assertEqual([i.duration for i in got.items], [120, 120])


class ClashRulesTest(unittest.TestCase):
    def test_rules(self):
        point = lambda h, m=0: Slot("x", at(13, h, m))
        long = lambda h, minutes: Slot("x", at(13, h), minutes)
        self.assertEqual(clash(point(9), point(9)), "same")
        self.assertEqual(clash(long(9, 120), long(9, 30)), "same")
        self.assertEqual(clash(long(9, 120), point(10)), "overlap")  # the training runs past the run
        self.assertEqual(clash(point(10), long(9, 120)), "overlap")  # order does not matter
        self.assertIsNone(clash(long(9, 120), point(11)))  # it ends exactly when the other starts: fits
        self.assertIsNone(clash(long(9, 60), long(11, 30)))
        self.assertEqual(clash(point(9), point(10)), "near")  # no duration known, one hour apart
        self.assertEqual(clash(point(9), point(9, 30)), "near")
        self.assertIsNone(clash(point(9), point(10, 1)))  # more than an hour
        self.assertIsNone(clash(long(9, 30), point(10)))  # known duration that ends in time: no question
        self.assertEqual(clash(point(9), long(10, 30)), "near")  # the earlier one has no known duration

    def test_repeating_reminders_are_expanded(self):
        weekly = Slot("treinar", at(12, 9), 120, "weekly")
        days = [o.start.day for o in occurrences(weekly)]
        self.assertEqual(days, [12, 19, 26])
        weekdays = Slot("x", at(16, 9), 0, "weekdays")  # a Friday: the weekend is skipped
        self.assertEqual([o.start.day for o in occurrences(weekdays)][:3], [16, 19, 20])

    def test_a_weekly_one_clashes_with_a_one_off_on_that_day(self):
        pending = [stored(1, "treinar", at(12, 9), 120, "weekly")]
        found = find_conflicts(pending, Slot("ligar pro Pedro", at(19, 10)))
        self.assertEqual([(c.kind, c.other.text) for c in found], [("overlap", "treinar")])
        self.assertEqual(find_conflicts(pending, Slot("ligar pro Pedro", at(20, 10))), [])

    def test_the_same_reminder_twice_is_not_a_clash(self):
        pending = [stored(1, "treinar", at(13, 9))]
        self.assertEqual(find_conflicts(pending, Slot("treinar", at(13, 9))), [])

    def test_each_stored_reminder_is_listed_once(self):
        pending = [stored(1, "treinar", at(12, 9), 0, "daily")]
        found = find_conflicts(pending, Slot("ligar pro Pedro", at(13, 9), 0, "daily"))
        self.assertEqual(len(found), 1)

    def test_the_question_says_what_clashes(self):
        pending = [stored(1, "treinar", at(13, 9), 120)]
        text = question(find_conflicts(pending, Slot("ligar pro Pedro", at(13, 10))), NOW)
        self.assertIn("“treinar” vai de 09:00 até 11:00", text)
        self.assertIn("“ligar pro Pedro” começa às 10:00", text)
        self.assertIn("Marco mesmo assim", text)
        near = question(find_conflicts([stored(1, "treinar", at(13, 9))], Slot("ligar pro Pedro", at(13, 10))), NOW)
        self.assertIn("1 hora antes", near)
        self.assertIn("Dá tempo dos dois", near)
        same = question(find_conflicts([stored(1, "treinar", at(13, 9))], Slot("ligar pro Pedro", at(13, 9))), NOW)
        self.assertIn("já está marcado", same)


class ClashConversationTest(unittest.TestCase):
    def flow(self, *pending):
        return ReminderFlow(pending=lambda: list(pending))

    def test_overlap_asks_then_yes_marks(self):
        flow = self.flow(stored(1, "treinar", at(13, 9), 120))
        asked = flow.start(1, "amanhã às 10 ligar pro Pedro", NOW)
        self.assertEqual(asked.kind, "conflito")
        got = flow.answer(1, "sim", NOW)
        self.assertIsInstance(got, Planned)
        self.assertEqual((got.text, got.due), ("ligar pro Pedro", at(13, 10)))

    def test_every_way_of_saying_go_ahead(self):
        for yes in ("sim", "pode", "pode marcar", "marca mesmo assim", "mesmo assim", "claro", "quero", "Sim!", "bora"):
            with self.subTest(yes):
                flow = self.flow(stored(1, "treinar", at(13, 9), 120))
                flow.start(1, "amanhã às 10 ligar pro Pedro", NOW)
                self.assertIsInstance(flow.answer(1, yes, NOW), Planned)

    def test_no_gives_up(self):
        for no in ("não", "deixa", "cancela", "melhor não"):
            with self.subTest(no):
                flow = self.flow(stored(1, "treinar", at(13, 9), 120))
                flow.start(1, "amanhã às 10 ligar pro Pedro", NOW)
                self.assertEqual(flow.answer(1, no, NOW), Dropped(CANCELLED))

    def test_another_time_is_checked_again(self):
        flow = self.flow(stored(1, "treinar", at(13, 9), 120))
        flow.start(1, "amanhã às 10 ligar pro Pedro", NOW)
        got = flow.answer(1, "às 11", NOW)  # the training ends at 11:00: it fits
        self.assertIsInstance(got, Planned)
        self.assertEqual(got.due, at(13, 11))
        flow.start(1, "amanhã às 10 ligar pro Pedro", NOW)
        again = flow.answer(1, "às 10 e meia", NOW)  # still inside the training: asked again
        self.assertEqual(again.kind, "conflito")
        self.assertIsInstance(flow.answer(1, "não, às 12", NOW), Planned)

    def test_a_new_time_keeps_the_first_day_of_a_repeating_reminder(self):
        # seen on the phone: "correr amanhã às 10, dias úteis" then "às 11" became "hoje às 11"
        flow = self.flow(stored(1, "treinar", at(13, 9), 120, "weekdays"))
        self.assertEqual(flow.start(1, "amanhã às 10 correr", NOW).kind, "repetir")
        self.assertEqual(flow.answer(1, "dias úteis", NOW).kind, "conflito")
        got = flow.answer(1, "às 11", NOW)
        self.assertIsInstance(got, Planned)
        self.assertEqual((got.due, got.repeat), (at(13, 11), "weekdays"))

    def test_a_new_time_keeps_the_day_of_a_series_and_a_weekly_one(self):
        flow = self.flow(stored(1, "treinar", at(14, 9), 120))
        flow.start(1, "toda segunda e quarta às 10 ligar pro Pedro", NOW)
        got = flow.answer(1, "às 11", NOW)
        self.assertIsInstance(got, PlannedSeries)
        self.assertEqual(sorted((i.due.day, i.due.hour) for i in got.items), [(12, 11), (14, 11)])

    def test_the_duration_survives_a_new_time(self):
        flow = self.flow(stored(1, "treinar", at(13, 9), 120))
        flow.start(1, "amanhã às 10 ligar pro Pedro por 30 minutos", NOW)
        got = flow.answer(1, "às 11", NOW)
        self.assertEqual((got.due, got.duration), (at(13, 11), 30))

    def test_near_without_a_duration_asks_do_they_fit(self):
        flow = self.flow(stored(1, "treinar", at(13, 9)))
        asked = flow.start(1, "amanhã às 10 ligar pro Pedro", NOW)
        self.assertEqual(asked.kind, "conflito")
        self.assertIn("Dá tempo dos dois", asked.question)

    def test_things_that_fit_are_marked_straight_away(self):
        for pending, said in (
            (stored(1, "treinar", at(13, 9), 60), "amanhã às 10 ligar pro Pedro"),          # ends exactly when the other starts
            (stored(1, "treinar", at(13, 9)), "amanhã às 11 ligar pro Pedro"),                # two hours apart
            (stored(1, "treinar", at(13, 9), 120), "amanhã às 11 ligar pro Pedro"),
            (stored(1, "treinar", at(14, 9), 120), "amanhã às 9 ligar pro Pedro"),            # another day
        ):
            with self.subTest(said):
                self.assertIsInstance(self.flow(pending).start(1, said, NOW), (Planned, PlannedSeries))

    def test_a_weekly_series_is_checked_day_by_day(self):
        flow = self.flow(stored(1, "treinar", at(14, 9), 120))  # Wednesday
        asked = flow.start(1, "toda segunda e quarta às 10 ligar pro Pedro", NOW)
        self.assertEqual(asked.kind, "conflito")
        got = flow.answer(1, "sim", NOW)
        self.assertIsInstance(got, PlannedSeries)
        self.assertEqual(len(got.items), 2)

    def test_several_clashes_are_listed(self):
        flow = self.flow(stored(1, "treinar", at(13, 9)), stored(2, "inglês", at(13, 10, 30)))
        asked = flow.start(1, "amanhã às 10 ligar pro Pedro", NOW)
        self.assertIn("1.", asked.question)
        self.assertIn("2.", asked.question)

    def test_an_unrelated_message_is_not_an_answer(self):
        flow = self.flow(stored(1, "treinar", at(13, 9), 120))
        flow.start(1, "amanhã às 10 ligar pro Pedro", NOW)
        self.assertIsNone(flow.answer(1, "que horas são?", NOW))
        self.assertFalse(flow.pending(1))

    def test_a_routine_asks_to_repeat_first_and_then_about_the_clash(self):
        flow = self.flow(stored(1, "treinar", at(13, 9), 120))
        self.assertEqual(flow.start(1, "amanhã às 10 correr", NOW).kind, "repetir")
        asked = flow.answer(1, "só dessa vez", NOW)
        self.assertEqual(asked.kind, "conflito")
        got = flow.answer(1, "sim", NOW)
        self.assertEqual((got.text, got.due, got.repeat), ("correr", at(13, 10), None))

    def test_no_pending_provider_means_no_check(self):
        self.assertIsInstance(ReminderFlow().start(1, "amanhã às 10 ligar pro Pedro", NOW), Planned)

    def test_the_model_path_is_checked_too(self):
        flow = self.flow(stored(1, "treinar", at(13, 9), 120))
        asked = flow.start(1, "me avisa amanhã às 10 de ligar pro Pedro", NOW, text="ligar pro Pedro", when="amanhã às 10")
        self.assertEqual(asked.kind, "conflito")
        got = flow.answer(1, "pode", NOW)
        self.assertEqual((got.text, got.due), ("ligar pro Pedro", at(13, 10)))


if __name__ == "__main__":
    unittest.main()
