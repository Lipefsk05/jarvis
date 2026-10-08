import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from jarvis.budget import Budget


class BudgetTest(unittest.TestCase):
    def make(self, tmp, cap=1.0, clock=None):
        return Budget(Path(tmp) / "state" / "usage.json", cap, 1.0, 5.0,
                      clock=clock or (lambda: datetime(2026, 10, 8, 12, 0)))

    def test_cost_math_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.make(tmp)
            cost = b.add(2_000_000, 100_000)  # 2*1 + 0.1*5 = 2.5
            self.assertAlmostEqual(cost, 2.5)
            self.assertAlmostEqual(self.make(tmp).spent_today(), 2.5)

    def test_explicit_cost_overrides_default_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.make(tmp)
            self.assertAlmostEqual(b.add(2_000_000, 0, cost_usd=0.0), 0.0)  # free provider answered
            self.assertAlmostEqual(b.add(1_000_000, 0, cost_usd=0.25), 0.25)
            self.assertAlmostEqual(b.spent_today(), 0.25)

    def test_blocks_at_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.make(tmp, cap=0.01)
            self.assertTrue(b.can_spend())
            b.add(10_000, 0)  # exactly 0.01
            self.assertFalse(b.can_spend())

    def test_no_cap_never_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.make(tmp, cap=None)
            b.add(10_000_000, 10_000_000)
            self.assertTrue(b.can_spend())
            self.assertFalse(b.should_warn())

    def test_warns_once_at_eighty_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.make(tmp, cap=1.0)
            b.add(500_000, 0)  # 0.5
            self.assertFalse(b.should_warn())
            b.add(400_000, 0)  # 0.9
            self.assertTrue(b.should_warn())
            self.assertFalse(b.should_warn())

    def test_resets_on_a_new_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            day = {"now": datetime(2026, 10, 8, 23, 59)}
            b = self.make(tmp, clock=lambda: day["now"])
            b.add(1_000_000, 0)
            self.assertAlmostEqual(b.spent_today(), 1.0)
            day["now"] = datetime(2026, 10, 9, 0, 1)
            self.assertEqual(b.spent_today(), 0.0)
            self.assertTrue(b.can_spend())

    def test_corrupt_file_is_treated_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "usage.json"
            path.parent.mkdir()
            path.write_text("{not json", encoding="utf-8")
            b = self.make(tmp)
            self.assertEqual(b.spent_today(), 0.0)

    def test_summary_mentions_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.make(tmp, cap=1.0)
            b.add(1000, 100)
            self.assertIn("US$ 1.00", b.summary())


if __name__ == "__main__":
    unittest.main()
