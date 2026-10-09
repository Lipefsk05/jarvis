import random
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jarvis.outbox import Outbox
from jarvis.reminder_text import ReminderVoice
from jarvis.reminders import CANCELLED, LATE, LOST, PENDING, SENT, ReminderStore
from jarvis.scheduler import EXPIRES, GRACE, plan, run_once

TZ = ZoneInfo("America/Sao_Paulo")
T0 = datetime(2026, 10, 9, 9, 0, tzinfo=TZ)


class FakeChannel:
    def __init__(self, name="telegram", fail=False):
        self.name, self.fail, self.sent = name, fail, []

    async def send(self, text):
        if self.fail:
            raise ConnectionError("down")
        self.sent.append(text)


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ReminderStore(Path(self._tmp.name) / "lembretes.json")
        self.channel = FakeChannel()
        self.outbox = Outbox([self.channel])
        self.voice = ReminderVoice(random.Random(1))

    def add(self, text, minutes_after_t0):
        return self.store.add(text, T0 + timedelta(minutes=minutes_after_t0), T0 - timedelta(days=3))

    async def tick(self, minutes_after_t0, delivered=None):
        return await run_once(self.store, self.outbox, self.voice, T0 + timedelta(minutes=minutes_after_t0), delivered)


class PlanTest(Base):
    def test_buckets_by_lateness(self):
        on = self.add("em dia", 0)
        late = self.add("atrasado", 0)
        lost = self.add("perdido", 0)
        now = T0 + EXPIRES + timedelta(minutes=1)
        # same due time, evaluate three different "nows" through the lateness boundaries
        self.assertEqual(plan([on], T0 + GRACE).on_time, [on])
        self.assertEqual(plan([late], T0 + GRACE + timedelta(seconds=1)).late, [late])
        self.assertEqual(plan([lost], now).lost, [lost])
        self.assertEqual(plan([late], T0 + EXPIRES).late, [late])


class RunOnceTest(Base):
    async def test_nothing_due_sends_nothing(self):
        self.add("depois", 60)
        self.assertEqual(await self.tick(0), 0)
        self.assertEqual(self.channel.sent, [])

    async def test_on_time_reminder_is_sent_once_and_closed(self):
        r = self.add("pagar o aluguel", 0)
        heard = []
        self.assertEqual(await self.tick(0, heard.append), 1)
        self.assertEqual(len(self.channel.sent), 1)
        self.assertIn("pagar o aluguel", self.channel.sent[0])
        self.assertEqual(heard, self.channel.sent)
        self.assertEqual(self.store.get(r.id).status, SENT)
        self.assertEqual(await self.tick(1), 0)  # never twice
        self.assertEqual(len(self.channel.sent), 1)

    async def test_trailing_punctuation_is_not_doubled(self):
        self.add("ir ao banco.", 0)
        await self.tick(0)
        self.assertNotIn("..", self.channel.sent[0])

    async def test_late_ones_arrive_in_one_marked_message(self):
        a, b = self.add("primeiro", 0), self.add("segundo", 30)
        await self.tick(300)  # bot was down for hours
        self.assertEqual(len(self.channel.sent), 1)
        text = self.channel.sent[0]
        self.assertIn("1. 09:00 — primeiro", text)
        self.assertIn("2. 09:30 — segundo", text)
        self.assertEqual(self.store.get(a.id).status, LATE)
        self.assertEqual(self.store.get(b.id).status, LATE)

    async def test_single_late_reminder_says_when_it_was_due(self):
        self.add("remédio", 0)
        await self.tick(60)
        self.assertIn("09:00", self.channel.sent[0])
        self.assertIn("remédio", self.channel.sent[0])

    async def test_expired_ones_are_reported_once_and_closed_as_lost(self):
        old = self.add("velho", 0)
        recent = self.add("recente", 60 * 30)
        await self.tick(60 * 30 + 60 * 20)  # old is 50 h late, recent is 20 min late
        self.assertEqual(len(self.channel.sent), 1)
        self.assertIn("recente", self.channel.sent[0])
        self.assertIn("há mais de 24 horas", self.channel.sent[0])
        self.assertIn("velho", self.channel.sent[0])
        self.assertEqual(self.store.get(old.id).status, LOST)
        self.assertEqual(self.store.get(recent.id).status, LATE)

    async def test_failed_delivery_keeps_reminders_pending_and_retries(self):
        r = self.add("importante", 0)
        self.channel.fail = True
        self.assertEqual(await self.tick(0), 0)
        self.assertEqual(self.store.get(r.id).status, PENDING)
        self.channel.fail = False
        self.assertEqual(await self.tick(1), 1)
        self.assertEqual(self.store.get(r.id).status, SENT)

    async def test_cancelled_reminders_are_not_sent(self):
        r = self.add("desisti", 0)
        self.store.cancel(r.id, T0 - timedelta(minutes=1))
        await self.tick(0)
        self.assertEqual(self.channel.sent, [])
        self.assertEqual(self.store.get(r.id).status, CANCELLED)

    async def test_several_at_the_same_time_share_one_message(self):
        self.add("um", 0), self.add("dois", 0)
        await self.tick(0)
        self.assertEqual(len(self.channel.sent), 1)
        self.assertIn("1.", self.channel.sent[0])
        self.assertIn("2.", self.channel.sent[0])


class OutboxTest(unittest.IsolatedAsyncioTestCase):
    async def test_falls_back_to_the_next_channel(self):
        voice, telegram = FakeChannel("voz", fail=True), FakeChannel("telegram")
        outbox = Outbox([telegram, voice], route=lambda: "voz")
        self.assertTrue(await outbox.deliver("oi"))
        self.assertEqual(telegram.sent, ["oi"])

    async def test_reports_failure_when_every_channel_fails(self):
        outbox = Outbox([FakeChannel("telegram", fail=True)])
        self.assertFalse(await outbox.deliver("oi"))

    async def test_unknown_preferred_channel_uses_the_default(self):
        telegram = FakeChannel("telegram")
        self.assertTrue(await Outbox([telegram], route=lambda: "nao-existe").deliver("oi"))


class VoiceTest(unittest.TestCase):
    def test_never_repeats_the_same_form_twice_in_a_row(self):
        voice = ReminderVoice(random.Random(3))
        r = ReminderStore(Path(tempfile.mkdtemp()) / "x.json").add("tomar água", T0 + timedelta(hours=1), T0)
        texts = [voice.on_time([r], T0 + timedelta(hours=1)) for _ in range(40)]
        self.assertTrue(all(a != b for a, b in zip(texts, texts[1:])))
        self.assertGreater(len(set(texts)), 2)

    def test_no_jokes_or_slang(self):
        voice = ReminderVoice(random.Random(5))
        r = ReminderStore(Path(tempfile.mkdtemp()) / "x.json").add("x", T0 + timedelta(hours=1), T0)
        for _ in range(50):
            text = voice.on_time([r], T0)
            self.assertNotIn("[[", text)
            self.assertNotIn("kkk", text.lower())
