import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis.gcal import CalendarError, Event
from jarvis.plan import DONE, PLANNED, POSTPONED, SKIPPED, DayPlan, PlanItem, PlanStore
from jarvis.task_calendar import DONE_MARK, TaskCalendar, event_id, safe_sync, wanted

TZ = ZoneInfo("America/Sao_Paulo")
TODAY = date(2026, 10, 16)
CAL = "tarefas@group.calendar.google.com"


class FakeCalendar:
    def __init__(self):
        self.items = {}   # id -> (title, day)
        self.writes, self.deletes = [], []
        self.fail = False

    def list_events(self, calendar, start, end):
        if self.fail:
            raise CalendarError("o Google respondeu 500", 500)
        return [Event(i, calendar, t, datetime.combine(d, datetime.min.time(), TZ),
                      datetime.combine(d + timedelta(days=1), datetime.min.time(), TZ), True)
                for i, (t, d) in self.items.items()
                if start.date() <= d < end.date()]

    def upsert_all_day(self, calendar, event_id_, title, day, description=""):
        self.writes.append((event_id_, title, day))
        self.items[event_id_] = (title, day)

    def delete(self, calendar, event_id_):
        self.deletes.append(event_id_)
        self.items.pop(event_id_, None)


def item(task_id, title, status=PLANNED):
    return PlanItem(task_id, title, status=status, area="empresa/dindin")


class TaskCalendarTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = PlanStore(Path(self._tmp.name) / "plano.json")
        self.fake = FakeCalendar()
        self.sync = TaskCalendar(self.fake, CAL, TZ)

    def plan(self, day, *items):
        self.store.put(DayPlan(day, list(items)), TODAY)

    def run_sync(self):
        return self.sync.sync(self.store, TODAY)

    def test_ids_are_stable_and_valid(self):
        self.assertEqual(event_id("^vc-capcut"), event_id("^vc-capcut"))
        self.assertNotEqual(event_id("a"), event_id("b"))
        self.assertRegex(event_id("^x"), r"^jvt[0-9a-f]{30}$")

    def test_planned_tasks_are_written_once_and_syncing_again_changes_nothing(self):
        self.plan(TODAY, item("^a", "Landing"))
        self.plan(TODAY + timedelta(days=1), item("^b", "Relatório"))
        self.assertEqual(self.run_sync(), (2, 0))
        self.assertEqual(self.fake.items[event_id("^a")], ("Landing", TODAY))
        self.assertEqual(self.run_sync(), (0, 0))

    def test_a_done_task_gets_a_check_and_stays(self):
        self.plan(TODAY, item("^a", "Landing"))
        self.run_sync()
        self.plan(TODAY, item("^a", "Landing", DONE))
        self.assertEqual(self.run_sync(), (1, 0))
        self.assertEqual(self.fake.items[event_id("^a")][0], DONE_MARK + "Landing")

    def test_a_task_that_slipped_moves_to_its_new_day_instead_of_duplicating(self):
        yesterday = TODAY - timedelta(days=1)
        self.fake.items[event_id("^a")] = ("Landing", yesterday)  # written yesterday
        self.plan(yesterday, item("^a", "Landing", POSTPONED))
        self.plan(TODAY, item("^a", "Landing"))
        self.assertEqual(self.run_sync(), (1, 0))
        self.assertEqual(self.fake.items[event_id("^a")], ("Landing", TODAY))
        self.assertEqual(len(self.fake.items), 1)

    def test_what_left_the_plan_is_removed_but_past_days_are_kept_as_a_record(self):
        yesterday = TODAY - timedelta(days=1)
        self.fake.items[event_id("^old")] = (DONE_MARK + "Ontem", yesterday)
        self.fake.items[event_id("^gone")] = ("Sumiu", TODAY + timedelta(days=2))
        self.fake.items["manual"] = ("Evento meu", TODAY + timedelta(days=2))  # not ours: never touched
        self.plan(TODAY, item("^a", "Landing"))
        self.assertEqual(self.run_sync(), (1, 1))
        self.assertIn(event_id("^old"), self.fake.items)
        self.assertNotIn(event_id("^gone"), self.fake.items)
        self.assertIn("manual", self.fake.items)

    def test_skipped_and_postponed_tasks_are_not_shown(self):
        self.plan(TODAY, item("^a", "A", SKIPPED), item("^b", "B", POSTPONED), item("^c", "C"))
        self.assertEqual(list(wanted(self.store, TODAY)), [event_id("^c")])

    def test_a_calendar_failure_is_swallowed_and_logged(self):
        self.fake.fail = True
        self.plan(TODAY, item("^a", "Landing"))
        with self.assertLogs("jarvis.task_calendar", "WARNING"):
            safe_sync(self.sync, self.store, TODAY)


if __name__ == "__main__":
    unittest.main()
