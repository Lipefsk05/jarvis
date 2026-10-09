import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis.reminder_request import Planned, plan_parts, plan_reminder
from jarvis.reminder_text import confirmation, listing
from jarvis.reminders import PENDING, ReminderStore
from jarvis.repeat import DAILY, WEEKDAYS_ONLY, WEEKLY, align_first, extract, label, next_occurrence
from jarvis.when import Ask

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 9, 11, 0, tzinfo=TZ)  # sexta-feira


def at(day, hour, minute=0, month=10):
    return datetime(2026, month, day, hour, minute, tzinfo=TZ)


class ExtractTest(unittest.TestCase):
    def test_daily_forms(self):
        for raw in ("todo dia às 8 tomar remédio", "todos os dias às 8 tomar remédio", "diariamente às 8 tomar remédio"):
            found = extract(raw)
            self.assertEqual(found.repeat, DAILY, raw)
            self.assertNotIn("dia", found.rest.lower().replace("diariamente", ""), raw)
        self.assertEqual(extract("todo dia às 8 tomar remédio").rest, "às 8 tomar remédio")

    def test_weekdays_forms(self):
        for raw in ("todo dia útil às 8 standup", "nos dias úteis às 8 standup", "de segunda a sexta às 8 standup",
                    "todos os dias úteis às 8 standup"):
            self.assertEqual(extract(raw).repeat, WEEKDAYS_ONLY, raw)
        self.assertEqual(extract("de segunda a sexta às 8 standup").rest, "às 8 standup")

    def test_weekly_keeps_the_weekday_as_the_first_date(self):
        for raw in ("toda segunda às 9 reunião", "todas as segundas às 9 reunião", "toda segunda-feira às 9 reunião"):
            found = extract(raw)
            self.assertEqual((found.repeat, found.rest), (WEEKLY, "segunda às 9 reunião"), raw)
        self.assertEqual(extract("todo sábado às 10 feira").rest, "sabado às 10 feira")

    def test_toda_semana_needs_a_weekday(self):
        self.assertIsInstance(extract("toda semana às 9 reunião").ask, Ask)
        found = extract("toda semana na sexta às 9 reunião")
        self.assertEqual((found.repeat, found.rest), (WEEKLY, "sexta às 9 reunião"))

    def test_toda_noite_is_daily_and_keeps_the_period(self):
        found = extract("toda noite às 9 tomar o remédio")
        self.assertEqual((found.repeat, found.rest), (DAILY, "noite às 9 tomar o remédio"))

    def test_monthly_is_a_question_not_a_guess(self):
        for raw in ("todo mês dia 5 pagar a luz", "todo dia 20 pagar o cartão", "mensalmente pagar a luz"):
            found = extract(raw)
            self.assertIsNone(found.repeat, raw)
            self.assertIsInstance(found.ask, Ask, raw)

    def test_no_repeat_words_means_untouched(self):
        found = extract("amanhã às 9 pagar o aluguel")
        self.assertEqual((found.rest, found.repeat, found.ask), ("amanhã às 9 pagar o aluguel", None, None))
        self.assertIsNone(extract("falar com todo mundo amanhã às 9").repeat)


class PlanTest(unittest.TestCase):
    def test_daily_goes_to_the_next_time_it_occurs(self):
        planned = plan_reminder("todo dia às 8 da manhã tomar remédio", NOW)
        self.assertEqual(planned, Planned("tomar remédio", at(10, 8), None, 0, False, DAILY))

    def test_time_only_keeps_the_usual_am_pm_question(self):
        self.assertEqual(plan_reminder("todo dia às 8 tomar remédio", NOW).kind, "ampm")

    def test_daily_later_today_starts_today(self):
        self.assertEqual(plan_reminder("todo dia às 19 correr", NOW).due, at(9, 19))

    def test_weekly_starts_on_the_named_day(self):
        planned = plan_reminder("toda segunda às 9 reunião de equipe", NOW)
        self.assertEqual((planned.due, planned.repeat, planned.text), (at(12, 9), WEEKLY, "reunião de equipe"))

    def test_weekdays_never_start_on_a_weekend(self):
        planned = plan_reminder("nos dias úteis às 8 standup", datetime(2026, 10, 9, 20, 0, tzinfo=TZ))  # Friday night
        self.assertEqual((planned.due, planned.repeat), (at(12, 8), WEEKDAYS_ONLY))  # Monday

    def test_repeat_with_advance_warning(self):
        planned = plan_reminder("toda segunda às 9 reunião, 10 min antes", NOW)
        self.assertEqual((planned.due, planned.event, planned.repeat), (at(12, 8, 50), at(12, 9), WEEKLY))

    def test_repeat_inside_the_model_phrase(self):
        planned = plan_parts("tomar remédio", "todo dia às 8 da manhã", 0, NOW)
        self.assertEqual((planned.due, planned.repeat), (at(10, 8), DAILY))

    def test_questions_pass_through(self):
        self.assertIsInstance(plan_reminder("todo mês pagar a luz às 9", NOW), Ask)
        self.assertIsInstance(plan_reminder("toda semana às 9 reunião", NOW), Ask)


class NextOccurrenceTest(unittest.TestCase):
    def test_daily_weekly_and_weekdays(self):
        self.assertEqual(next_occurrence(at(9, 8), DAILY, NOW), at(10, 8))
        self.assertEqual(next_occurrence(at(5, 8), DAILY, NOW), at(10, 8))  # skips what already passed
        self.assertEqual(next_occurrence(at(5, 9), WEEKLY, NOW), at(12, 9))
        self.assertEqual(next_occurrence(at(9, 8), WEEKDAYS_ONLY, at(9, 9)), at(12, 8))  # Friday -> Monday

    def test_the_warning_time_decides_not_the_event(self):
        # Event at 9:00 with a 10 min warning: at 8:55 the warning for today's 9:00 is gone, so move on.
        self.assertEqual(next_occurrence(at(9, 9), DAILY, at(9, 8, 55), timedelta(minutes=10)), at(10, 9))

    def test_align_first_only_touches_weekdays_only(self):
        self.assertEqual(align_first(at(10, 8), WEEKDAYS_ONLY), at(12, 8))  # Saturday
        self.assertEqual(align_first(at(10, 8), DAILY), at(10, 8))

    def test_labels(self):
        self.assertEqual(label(DAILY, at(9, 8)), "todos os dias")
        self.assertEqual(label(WEEKDAYS_ONLY, at(9, 8)), "nos dias úteis")
        self.assertEqual(label(WEEKLY, at(12, 8)), "toda segunda-feira")
        self.assertEqual(label(WEEKLY, at(10, 8)), "todo sábado")


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "l.json"
        self.store = ReminderStore(self.path)

    def test_closing_a_repeating_one_moves_it_to_the_next_occurrence(self):
        item = self.store.add("tomar remédio", at(10, 8), NOW, repeat=DAILY)
        self.store.close(item.id, "enviado", at(10, 8, 0))
        again = self.store.get(item.id)
        self.assertEqual((again.status, again.due), (PENDING, at(11, 8)))
        self.assertEqual(self.store.pending(), [again])

    def test_with_a_warning_both_dates_move_and_the_gap_stays(self):
        item = self.store.add("reunião", at(12, 8, 50), NOW, event=at(12, 9), repeat=WEEKLY)
        self.store.close(item.id, "enviado", at(12, 8, 50))
        again = self.store.get(item.id)
        self.assertEqual((again.due, again.event), (at(19, 8, 50), at(19, 9)))

    def test_late_delivery_skips_the_missed_occurrences(self):
        item = self.store.add("tomar remédio", at(10, 8), NOW, repeat=DAILY)
        self.store.close(item.id, "atrasado", at(14, 12))  # bot was down for days
        self.assertEqual(self.store.get(item.id).due, at(15, 8))

    def test_a_plain_reminder_still_closes(self):
        item = self.store.add("uma vez", at(10, 8), NOW)
        self.store.close(item.id, "enviado", at(10, 8))
        self.assertEqual(self.store.get(item.id).status, "enviado")

    def test_survives_a_restart_and_cancel_ends_the_series(self):
        item = self.store.add("tomar remédio", at(10, 8), NOW, repeat=DAILY)
        again = ReminderStore(self.path).get(item.id)
        self.assertEqual(again.repeat, DAILY)
        cancelled = ReminderStore(self.path).cancel(item.id, NOW)
        self.assertEqual(cancelled.status, "cancelado")

    def test_same_text_and_time_with_a_different_repeat_is_not_a_duplicate(self):
        once = self.store.add("x", at(10, 8), NOW)
        daily = self.store.add("x", at(10, 8), NOW, repeat=DAILY)
        self.assertNotEqual(once.id, daily.id)


class TextTest(unittest.TestCase):
    def test_confirmation_and_listing_say_it_repeats(self):
        store = ReminderStore(Path(tempfile.mkdtemp()) / "l.json")
        item = store.add("tomar remédio", at(10, 8), NOW, repeat=DAILY)
        self.assertIn("Repito todos os dias", confirmation(item, NOW))
        self.assertIn("(repete todos os dias)", listing([item], NOW))
        plain = store.add("uma vez", at(10, 9), NOW)
        self.assertNotIn("epit", confirmation(plain, NOW))


if __name__ == "__main__":
    unittest.main()
