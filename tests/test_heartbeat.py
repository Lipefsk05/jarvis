import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jarvis.heartbeat import Outage, find_outage, read_last, write_beat

T0 = datetime(2026, 10, 9, 2, 10, tzinfo=timezone.utc)


class HeartbeatTest(unittest.TestCase):
    def test_write_overwrites_one_value_and_reads_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "heartbeat"
            self.assertIsNone(read_last(path))
            write_beat(path, T0)
            write_beat(path, T0 + timedelta(minutes=1))
            self.assertEqual(read_last(path), T0 + timedelta(minutes=1))
            self.assertEqual(len(path.read_text().splitlines()), 1)

    def test_garbage_file_reads_as_no_beat(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "heartbeat"
            path.write_text("lixo")
            self.assertIsNone(read_last(path))

    def test_short_gaps_and_first_run_are_not_outages(self):
        self.assertIsNone(find_outage(None, T0))
        self.assertIsNone(find_outage(T0, T0 + timedelta(minutes=9)))

    def test_long_gap_is_an_outage_and_reads_naturally(self):
        outage = find_outage(T0, T0 + timedelta(hours=5, minutes=35))
        self.assertEqual(outage, Outage(T0, T0 + timedelta(hours=5, minutes=35)))
        self.assertEqual(outage.describe(), "das 02:10 às 07:45")
        across = Outage(T0, T0 + timedelta(days=1))
        self.assertEqual(across.describe(), "de 09/10 02:10 até 10/10 02:10")
