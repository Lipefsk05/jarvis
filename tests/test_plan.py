import tempfile
import unittest
from datetime import date
from pathlib import Path

from jarvis.plan import (
    MAX_CAPACITY, MIN_CAPACITY, NOTEBOOK, PHONE, POSTPONED, DayPlan, Load, PlanItem, PlanStore,
)

DAY = date(2026, 10, 14)  # a Wednesday


class CapacityTest(unittest.TestCase):
    def test_starts_low_sunday_holds_one_less_and_saturday_is_zero(self):
        load = Load()
        self.assertEqual(load.capacity(date(2026, 10, 14)), 3)
        self.assertEqual(load.capacity(date(2026, 10, 18)), 2)  # Sunday
        self.assertEqual(load.capacity(date(2026, 10, 17)), 0)  # Saturday

    def test_two_full_days_raise_it_two_short_days_lower_it(self):
        load = Load()
        load.record(DAY, True)
        self.assertEqual(load.base, 3)
        load.record(DAY, True)
        self.assertEqual((load.base, load.full), (4, 0))
        load.record(DAY, False)
        load.record(DAY, False)
        self.assertEqual((load.base, load.short), (3, 0))

    def test_a_break_in_the_streak_starts_it_over(self):
        load = Load()
        load.record(DAY, True)
        load.record(DAY, False)
        load.record(DAY, True)
        self.assertEqual(load.base, 3)

    def test_capacity_has_a_floor_and_a_ceiling(self):
        load = Load(base=MIN_CAPACITY)
        for _ in range(6):
            load.record(DAY, False)
        self.assertEqual(load.base, MIN_CAPACITY)
        load = Load(base=MAX_CAPACITY)
        for _ in range(6):
            load.record(DAY, True)
        self.assertEqual(load.base, MAX_CAPACITY)
        self.assertEqual(Load(base=MIN_CAPACITY).capacity(date(2026, 10, 18)), MIN_CAPACITY)  # Sunday never reaches 0


class StoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "plano.json"
        self.store = PlanStore(self.path)

    def test_items_roundtrip_and_mark(self):
        plan = DayPlan(DAY, items=[PlanItem("^jv-agenda", "  Agenda   e e-mail ", PHONE, minutes=30, area="pessoal/jarvis")])
        self.store.put(plan)
        again = PlanStore(self.path)
        item = again.get(DAY).items[0]
        self.assertEqual((item.title, item.needs, item.minutes, item.area), ("Agenda e e-mail", PHONE, 30, "pessoal/jarvis"))
        self.assertEqual(again.mark(DAY, "^jv-agenda", POSTPONED).status, POSTPONED)
        self.assertEqual(again.get(DAY).open_items(), [])
        self.assertIsNone(again.mark(DAY, "nope", POSTPONED))

    def test_load_survives_a_restart(self):
        self.store.load.base, self.store.load.settled = 5, DAY
        self.store.save(DAY)
        again = PlanStore(self.path)
        self.assertEqual((again.load.base, again.load.settled), (5, DAY))

    def test_a_file_from_the_anchor_model_still_loads(self):
        self.path.write_text(
            '{"days": [{"day": "2026-10-14", "told": {"arrive_work": "2026-10-14T09:00:00-03:00"}, "items": ['
            '{"task_id": "^x", "title": "Algo", "needs": "notebook", "block": "casa_noite", "status": "planejado", '
            '"minutes": 25, "maybe": false}]}]}', encoding="utf-8")
        item = PlanStore(self.path).get(DAY).items[0]
        self.assertEqual((item.task_id, item.needs, item.minutes), ("^x", NOTEBOOK, 25))

    def test_invalid_item_values(self):
        with self.assertRaises(ValueError):
            PlanItem("a", "b", needs="geladeira")
        with self.assertRaises(ValueError):
            PlanItem("a", "b", status="talvez")

    def test_corrupt_file_is_set_aside(self):
        self.path.write_text("{nao é json", encoding="utf-8")
        store = PlanStore(self.path)
        self.assertIsNone(store.get(DAY))
        self.assertTrue(self.path.with_suffix(".corrupt").exists())

    def test_old_days_are_dropped_on_save(self):
        self.store.put(DayPlan(date(2026, 9, 1)))
        self.store.put(DayPlan(DAY))
        self.assertIsNone(PlanStore(self.path).get(date(2026, 9, 1)))

    def test_drop_after_keeps_the_day_itself(self):
        for n in (14, 15, 16):
            self.store.put(DayPlan(date(2026, 10, n)))
        self.store.drop_after(DAY)
        self.assertEqual([p.day.day for p in self.store.days()], [14])


if __name__ == "__main__":
    unittest.main()
