import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis.reminders import (
    CANCELLED, KEEP_CLOSED_DAYS, LATE, LOST, MAX_PENDING, MAX_TEXT_CHARS, PENDING, SENT,
    ReminderError, ReminderStore,
)

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 9, 11, 0, tzinfo=TZ)


def later(**kw):
    return NOW + timedelta(**kw)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "lembretes.json"
        self.store = ReminderStore(self.path)

    def test_add_lists_pending_sorted_by_due(self):
        b = self.store.add("segundo", later(hours=2), NOW)
        a = self.store.add("primeiro", later(hours=1), NOW)
        self.assertEqual([r.text for r in self.store.pending()], ["primeiro", "segundo"])
        self.assertEqual((a.id, b.id), (2, 1))
        self.assertEqual(a.status, PENDING)

    def test_survives_a_restart(self):
        self.store.add("pagar o aluguel", later(days=1), NOW)
        again = ReminderStore(self.path)
        self.assertEqual([r.text for r in again.pending()], ["pagar o aluguel"])
        self.assertEqual(again.pending()[0].due, later(days=1))
        self.assertEqual(again.add("outro", later(days=2), NOW).id, 2)

    def test_ids_are_never_reused(self):
        first = self.store.add("a", later(hours=1), NOW)
        self.store.cancel(first.id, NOW)
        self.assertEqual(self.store.add("b", later(hours=1), NOW).id, 2)
        self.assertEqual(ReminderStore(self.path).add("c", later(hours=1), NOW).id, 3)

    def test_rejects_bad_input_with_a_user_safe_message(self):
        with self.assertRaises(ReminderError):
            self.store.add("   ", later(hours=1), NOW)
        with self.assertRaises(ReminderError):
            self.store.add("x", NOW, NOW)
        with self.assertRaises(ReminderError):
            self.store.add("x", NOW - timedelta(minutes=1), NOW)
        with self.assertRaises(ValueError):
            self.store.add("x", datetime(2026, 10, 10, 9, 0), NOW)  # naive datetime

    def test_text_is_cleaned_and_capped(self):
        reminder = self.store.add("  linha1\n\n linha2\x00  fim ", later(hours=1), NOW)
        self.assertEqual(reminder.text, "linha1 linha2 fim")
        self.assertEqual(len(self.store.add("y" * 5000, later(hours=2), NOW).text), MAX_TEXT_CHARS)

    def test_same_text_and_time_is_not_duplicated(self):
        one = self.store.add("tomar remédio", later(hours=3), NOW)
        two = self.store.add("tomar remédio", later(hours=3), NOW)
        self.assertEqual(one.id, two.id)
        self.assertEqual(len(self.store.pending()), 1)
        self.store.add("tomar remédio", later(hours=4), NOW)  # other time: a different reminder
        self.assertEqual(len(self.store.pending()), 2)

    def test_pending_limit(self):
        for i in range(MAX_PENDING):
            self.store.add(f"n{i}", later(hours=1, minutes=i), NOW)
        with self.assertRaises(ReminderError):
            self.store.add("um a mais", later(days=2), NOW)

    def test_due_returns_only_pending_that_are_due(self):
        self.store.add("cedo", later(minutes=5), NOW)
        self.store.add("tarde", later(hours=5), NOW)
        self.assertEqual(self.store.due(NOW), [])
        self.assertEqual([r.text for r in self.store.due(later(minutes=10))], ["cedo"])
        self.assertEqual(len(self.store.due(later(days=1))), 2)

    def test_close_and_cancel_only_work_on_pending(self):
        a = self.store.add("a", later(minutes=5), NOW)
        b = self.store.add("b", later(minutes=6), NOW)
        c = self.store.add("c", later(minutes=7), NOW)
        self.assertEqual(self.store.close(a.id, SENT, later(minutes=5)).status, SENT)
        self.assertEqual(self.store.close(b.id, LATE, later(hours=3)).status, LATE)
        self.assertEqual(self.store.cancel(c.id, later(minutes=1)).status, CANCELLED)
        for item in (a, b, c):
            self.assertIsNone(self.store.cancel(item.id, later(hours=4)))
            self.assertIsNone(self.store.close(item.id, SENT, later(hours=4)))
        self.assertIsNone(self.store.cancel(999, NOW))
        self.assertEqual(self.store.pending(), [])
        with self.assertRaises(ValueError):
            self.store.close(a.id, CANCELLED, NOW)  # cancel has its own method

    def test_closed_since_for_the_daily_summary(self):
        a = self.store.add("a", later(minutes=5), NOW)
        b = self.store.add("b", later(minutes=6), NOW)
        self.store.close(a.id, LOST, later(days=2))
        self.store.close(b.id, SENT, later(days=2, minutes=1))
        self.assertEqual([r.text for r in self.store.closed_since(later(days=1))], ["a", "b"])
        self.assertEqual([r.text for r in self.store.closed_since(later(days=1), LOST)], ["a"])
        self.assertEqual(self.store.closed_since(later(days=3)), [])

    def test_old_closed_reminders_are_pruned_but_pending_never(self):
        old = self.store.add("velho", later(minutes=5), NOW)
        keep = self.store.add("futuro", later(days=90), NOW)
        self.store.close(old.id, SENT, later(minutes=5))
        far = later(days=KEEP_CLOSED_DAYS + 1)
        self.store.add("gatilho do salvamento", later(days=91), far)
        self.assertIsNone(self.store.get(old.id))
        self.assertIsNotNone(self.store.get(keep.id))

    def test_corrupt_file_is_quarantined_not_overwritten(self):
        self.path.write_text("{não é json", encoding="utf-8")
        store = ReminderStore(self.path)
        self.assertEqual(store.pending(), [])
        self.assertTrue(self.path.with_suffix(".corrupt").exists())
        self.assertEqual(self.path.with_suffix(".corrupt").read_text(encoding="utf-8"), "{não é json")
        self.assertEqual(store.add("novo", later(hours=1), NOW).id, 1)

    def test_wrong_shape_is_also_quarantined(self):
        self.path.write_text(json.dumps({"items": [{"id": 1}], "next_id": 2}), encoding="utf-8")
        self.assertEqual(ReminderStore(self.path).pending(), [])
        self.assertTrue(self.path.with_suffix(".corrupt").exists())

    def test_file_is_private(self):
        self.store.add("segredo", later(hours=1), NOW)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)


class EventFieldTest(unittest.TestCase):
    def test_event_round_trips_and_old_files_without_it_still_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lembretes.json"
            store = ReminderStore(path)
            store.add("pg jovem", later(hours=8), NOW, event=later(hours=8, minutes=10))
            self.assertEqual(ReminderStore(path).pending()[0].event, later(hours=8, minutes=10))
            raw = json.loads(path.read_text(encoding="utf-8"))
            for item in raw["items"]:
                del item["event"]  # a file written before the field existed
            path.write_text(json.dumps(raw), encoding="utf-8")
            self.assertIsNone(ReminderStore(path).pending()[0].event)


class SearchTest(unittest.TestCase):
    def test_finds_pending_by_words_ignoring_accents_and_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ReminderStore(Path(tmp) / "x.json")
            a = store.add("Pagar o ALUGUEL", later(hours=1), NOW)
            store.add("Consulta no médico", later(hours=2), NOW)
            done = store.add("aluguel do carro", later(hours=3), NOW)
            store.cancel(done.id, NOW)
            self.assertEqual([r.id for r in store.search("aluguel")], [a.id])
            self.assertEqual([r.text for r in store.search("medico")], ["Consulta no médico"])
            self.assertEqual(store.search("pagar aluguel")[0].id, a.id)
            self.assertEqual(store.search("   "), [])
            self.assertEqual(store.search("inexistente"), [])
