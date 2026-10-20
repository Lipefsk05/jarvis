import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jarvis import morning as mo
from jarvis import weather as wt
from jarvis import worker as w
from jarvis.digest import Digest
from jarvis.mail import Mail, MailAccount

TZ = timezone(timedelta(hours=-3))
NOW = datetime(2026, 10, 21, 7, 5, tzinfo=TZ)  # a Wednesday


class WeatherTest(unittest.TestCase):
    def fake_open(self, payload):
        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return lambda url, timeout: Resp(json.dumps(payload).encode())

    def test_reads_the_forecast_and_warns_about_rain(self):
        daily = {"daily": {"weather_code": [63], "temperature_2m_max": [27.4], "temperature_2m_min": [18.2], "precipitation_probability_max": [77]}}
        forecast = wt.fetch(-19.9, -43.9, "America/Sao_Paulo", opener=self.fake_open(daily))
        text = wt.format_forecast(forecast, "Belo Horizonte")
        self.assertEqual(text, "Belo Horizonte: chuva, de 18° a 27°, 77% de chance de chuva (leve o guarda-chuva).")

    def test_dry_day_has_no_umbrella_and_unknown_code_is_harmless(self):
        text = wt.format_forecast(wt.Forecast(15, 28, 10, 999), "BH")
        self.assertEqual(text, "BH: tempo variável, de 15° a 28°.")


class MorningTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = w.JobStore(root / "trabalhos.json")
        self.sent = []

        async def deliver(text):
            self.sent.append(text)
            return True

        async def runner(request, cwd, timeout, **kw):
            return w.Outcome(True, "Importantes: nada.")

        self.worker = w.Worker(self.store, root, deliver, lambda: NOW, runner=runner)
        self.deliver, self.root = deliver, root
        account = MailAccount("profissional", "a@x.com", "p")
        mail = Mail("Fulano", "Oi", "", "texto", NOW - timedelta(hours=1))
        self.digest = Digest((account,), self.worker, deliver, lambda: NOW, root / "digest.json", fetch=lambda a, d: [mail])

    def make(self, providers, digest="default", **kw):
        return mo.Morning(providers, self.digest if digest == "default" else digest, self.worker, self.deliver,
                          lambda: NOW, self.root / "resumao.json", hour=7, mail_wait_s=5, **kw)

    async def test_one_message_with_every_section_and_the_mail_summary(self):
        async def clima(): return "BH: nublado."
        async def agenda(): return "Agenda de hoje\n10:00  Reunião"
        import asyncio
        runner = asyncio.create_task(self.worker.run())
        morning = self.make([("Clima", clima), ("Agenda", agenda)])
        self.assertTrue(await morning.run())
        runner.cancel()
        self.assertEqual(len(self.sent), 1)  # the e-mail summary is inside, not a message of its own
        text = self.sent[0]
        self.assertTrue(text.startswith("Bom dia, senhor. Resumo de quarta, 21/10:"))
        self.assertIn("Clima\nBH: nublado.", text)
        self.assertIn("Agenda de hoje\n10:00  Reunião", text)  # the title is not repeated
        self.assertIn("E-mails — profissional\nImportantes: nada.", text)
        self.assertFalse(morning.due())

    async def test_a_failing_section_is_said_and_does_not_cost_the_rest(self):
        async def clima(): raise OSError("offline")
        async def plano(): return "Plano de hoje, senhor:\n- x"
        morning = self.make([("Clima", clima), ("Plano", plano)], digest=None)
        await morning.run()
        text = self.sent[0]
        self.assertIn("Plano de hoje", text)
        self.assertIn("Não consegui trazer: clima.", text)

    async def test_empty_sections_are_left_out(self):
        async def vazio(): return None
        morning = self.make([("Lembretes", vazio)], digest=None)
        await morning.run()
        self.assertNotIn("Lembretes", self.sent[0])

    def test_due_once_a_day_after_the_hour(self):
        morning = self.make([], digest=None)
        self.assertTrue(morning.due())
        morning._mark(NOW)
        self.assertFalse(morning.due())

    async def test_not_marked_when_delivery_fails(self):
        async def down(text): return False
        morning = mo.Morning([], None, self.worker, down, lambda: NOW, self.root / "resumao.json", hour=7)
        self.assertFalse(await morning.run())
        self.assertTrue(morning.due())


if __name__ == "__main__":
    unittest.main()
