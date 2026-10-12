import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis.plan import (
    ANY, BUS, HOME, NOTEBOOK, PHONE, POSTPONED, WORK, Block, DayPlan, Habits, PlanItem, PlanStore,
    build_blocks, resolve_anchors,
)

TZ = ZoneInfo("America/Sao_Paulo")
DAY = date(2026, 10, 14)  # a Wednesday
H = Habits()


def at(h, m=0):
    return datetime(2026, 10, 14, h, m, tzinfo=TZ)


class AnchorsTest(unittest.TestCase):
    def test_nothing_told_assumes_late_arrival(self):
        moments, estimated = resolve_anchors(DAY, {}, H, TZ)
        self.assertEqual(moments["arrive_work"], at(10, 30))
        self.assertEqual(moments["leave_work"], at(16, 30))
        self.assertEqual(moments["arrive_home"], at(17, 20))
        self.assertEqual(moments["leave_home"], at(9, 40))
        self.assertTrue(all(estimated.values()))

    def test_arrival_moves_the_rest_of_the_day(self):
        moments, estimated = resolve_anchors(DAY, {"arrive_work": at(9, 10)}, H, TZ)
        self.assertEqual(moments["leave_work"], at(15, 10))
        self.assertEqual(moments["arrive_home"], at(16, 0))
        self.assertFalse(estimated["arrive_work"])
        self.assertTrue(estimated["leave_work"])

    def test_leaving_home_moves_the_rest_of_the_day(self):
        moments, estimated = resolve_anchors(DAY, {"leave_home": at(8, 15)}, H, TZ)
        self.assertEqual(moments["arrive_work"], at(9, 5))
        self.assertEqual(moments["leave_work"], at(15, 5))
        self.assertFalse(estimated["leave_home"])
        self.assertTrue(estimated["arrive_work"])

    def test_two_told_anchors_bound_the_guess_between_them(self):
        told = {"leave_home": at(8, 0), "leave_work": at(14, 0)}
        moments, _ = resolve_anchors(DAY, told, H, TZ)
        self.assertEqual(moments["arrive_work"], at(8, 50))
        self.assertEqual(moments["arrive_home"], at(14, 50))

    def test_told_later_anchor_pulls_guesses_earlier(self):
        moments, _ = resolve_anchors(DAY, {"arrive_home": at(15, 50)}, H, TZ)
        self.assertEqual(moments["arrive_home"], at(15, 50))
        self.assertEqual(moments["leave_work"], at(15, 0))
        self.assertEqual(moments["arrive_work"], at(9, 0))
        self.assertEqual(moments["leave_home"], at(8, 10))

    def test_told_anchors_out_of_order_are_rejected(self):
        with self.assertRaises(ValueError):
            resolve_anchors(DAY, {"arrive_work": at(10), "leave_work": at(9)}, H, TZ)

    def test_unknown_anchor_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_anchors(DAY, {"lunch": at(12)}, H, TZ)


class BlocksTest(unittest.TestCase):
    def test_five_contiguous_blocks_anchored_on_arrival(self):
        blocks = build_blocks(DAY, {"arrive_work": at(9, 30)}, H, TZ)
        self.assertEqual([b.kind for b in blocks],
                         ["casa_manha", "onibus_ida", "trabalho", "onibus_volta", "casa_noite"])
        for a, b in zip(blocks, blocks[1:]):
            self.assertEqual(a.end, b.start)
        self.assertEqual(blocks[1].start, at(8, 40))
        self.assertEqual(blocks[2].start, at(9, 30))
        self.assertTrue(blocks[1].estimated)  # leaving home was not told
        self.assertTrue(blocks[3].estimated)  # leaving work was not told

    def test_all_told_means_no_estimated_edge_on_the_commute(self):
        told = {"leave_home": at(8, 40), "arrive_work": at(9, 30), "leave_work": at(15, 40), "arrive_home": at(16, 35)}
        blocks = build_blocks(DAY, told, H, TZ)
        self.assertFalse(any(b.estimated for b in blocks[1:]))

    def test_evening_never_ends_before_arriving_home(self):
        blocks = build_blocks(DAY, {"arrive_home": at(23, 0), "leave_work": at(22, 0)}, H, TZ)
        self.assertGreaterEqual(blocks[-1].end, blocks[-1].start)

    def test_places_accept_the_right_tasks(self):
        blocks = {b.kind: b for b in build_blocks(DAY, {}, H, TZ)}
        self.assertTrue(blocks["casa_noite"].accepts(NOTEBOOK))
        self.assertFalse(blocks["onibus_ida"].accepts(NOTEBOOK))
        self.assertTrue(blocks["onibus_volta"].accepts(PHONE))
        self.assertTrue(blocks["trabalho"].accepts(ANY))
        self.assertEqual(blocks["onibus_ida"].place, BUS)
        self.assertEqual(blocks["trabalho"].place, WORK)
        self.assertEqual(blocks["casa_manha"].place, HOME)

    def test_block_minutes(self):
        block = Block("x", HOME, at(10), at(11, 30), False)
        self.assertEqual(block.minutes, 90)


class CapacityTest(unittest.TestCase):
    def test_starts_low_and_saturday_is_zero(self):
        self.assertEqual(H.capacity(date(2026, 10, 14)), 3)
        self.assertEqual(H.capacity(date(2026, 10, 18)), 2)  # Sunday
        self.assertEqual(H.capacity(date(2026, 10, 17)), 0)  # Saturday


class StoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "plano.json"
        self.store = PlanStore(self.path)

    def test_tell_persists_and_survives_restart(self):
        self.store.tell(DAY, "arrive_work", at(9, 20), H, TZ)
        again = PlanStore(self.path)
        self.assertEqual(again.get(DAY).told["arrive_work"], at(9, 20))

    def test_tell_rejects_contradiction_and_keeps_old_state(self):
        self.store.tell(DAY, "arrive_work", at(10), H, TZ)
        with self.assertRaises(ValueError):
            self.store.tell(DAY, "leave_work", at(9), H, TZ)
        self.assertNotIn("leave_work", self.store.get(DAY).told)

    def test_tell_requires_aware_datetime(self):
        with self.assertRaises(ValueError):
            self.store.tell(DAY, "arrive_work", datetime(2026, 10, 14, 9), H, TZ)

    def test_items_roundtrip_and_mark(self):
        plan = DayPlan(DAY, items=[PlanItem("^jv-agenda", "  Agenda   e e-mail ", PHONE, "onibus_ida", minutes=30)])
        self.store.put(plan)
        again = PlanStore(self.path)
        item = again.get(DAY).items[0]
        self.assertEqual((item.title, item.needs, item.minutes), ("Agenda e e-mail", PHONE, 30))
        self.assertEqual(again.mark(DAY, "^jv-agenda", POSTPONED).status, POSTPONED)
        self.assertEqual(again.get(DAY).open_items(), [])
        self.assertIsNone(again.mark(DAY, "nope", POSTPONED))

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


if __name__ == "__main__":
    unittest.main()
