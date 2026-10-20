import asyncio
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from jarvis import worker as w

NOW = datetime(2026, 10, 19, 22, 0)


def ok(text="resposta"):
    async def runner(request, cwd, timeout):
        return w.Outcome(True, text)
    return runner


class ParseOutputTest(unittest.TestCase):
    def test_reads_the_result(self):
        out = json.dumps({"is_error": False, "result": " 22 "})
        self.assertEqual(w.parse_output(0, out, ""), w.Outcome(True, "22"))

    def test_error_flag_or_empty_result_is_a_failure(self):
        self.assertFalse(w.parse_output(0, json.dumps({"is_error": True, "result": "boom"}), "").ok)
        self.assertFalse(w.parse_output(0, json.dumps({"is_error": False, "result": " "}), "").ok)

    def test_garbage_never_raises(self):
        self.assertFalse(w.parse_output(1, "not json", "").ok)
        self.assertFalse(w.parse_output(1, "[1]", "").ok)

    def test_expired_login_and_quota_get_their_own_reason(self):
        self.assertIn("login", w.parse_output(1, "", "OAuth session expired").text)
        self.assertIn("cota", w.parse_output(1, json.dumps({"is_error": True, "result": "Usage limit reached"}), "").text)


class WorkerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "trabalhos.json"
        self.store = w.JobStore(self.path)
        self.sent = []

    def make(self, runner=None, **kw):
        async def deliver(text):
            self.sent.append(text)
            return True
        return w.Worker(self.store, Path(self.tmp.name), deliver, lambda: NOW, runner=runner or ok(), **kw)

    async def drain(self, worker):
        task = asyncio.create_task(worker.run())
        for _ in range(50):
            await asyncio.sleep(0.01)
            if not self.store.open_jobs():
                break
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_runs_a_job_and_delivers_the_answer(self):
        worker = self.make(ok("3 tarefas"))
        job = worker.submit("  quantas tarefas do dindin?  ")
        self.assertEqual(job.request, "quantas tarefas do dindin?")
        await self.drain(worker)
        self.assertEqual(self.store.get(job.id).status, w.DONE)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("3 tarefas", self.sent[0])

    async def test_a_failure_is_delivered_as_a_failure(self):
        async def broken(request, cwd, timeout):
            raise RuntimeError("x")
        worker = self.make(broken)
        job = worker.submit("algo")
        await self.drain(worker)
        self.assertEqual(self.store.get(job.id).status, w.FAILED)
        self.assertIn("Não consegui concluir a pesquisa", self.sent[0])
        self.assertNotIn("Trabalhador", self.sent[0])

    async def test_rejects_empty_full_queue_and_daily_cap(self):
        worker = self.make(daily_max=4)
        with self.assertRaises(w.WorkerError):
            worker.submit("   ")
        for i in range(w.MAX_QUEUE):
            worker.submit(f"pedido {i}")
        with self.assertRaises(w.WorkerError) as ctx:
            worker.submit("mais um")
        self.assertIn("em andamento", str(ctx.exception))
        await self.drain(worker)
        worker.submit("o quarto")
        with self.assertRaises(w.WorkerError) as ctx:
            worker.submit("o quinto")
        self.assertIn("hoje", str(ctx.exception))

    async def test_restart_marks_open_jobs_interrupted_and_keeps_ids(self):
        worker = self.make()
        first = worker.submit("um")
        again = w.JobStore(self.path)
        self.assertEqual(again.get(first.id).status, w.INTERRUPTED)
        self.assertEqual(again.add("dois", NOW).id, first.id + 1)


class FindClaudeTest(unittest.TestCase):
    def test_env_override_wins(self):
        self.assertEqual(w.find_claude({"JARVIS_CLAUDE_BIN": "/x/claude", "PATH": ""}), "/x/claude")

    def test_falls_back_to_local_bin_when_the_path_is_short(self):
        with tempfile.TemporaryDirectory() as home:
            binary = Path(home) / ".local" / "bin" / "claude"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\n")
            self.assertEqual(w.find_claude({"PATH": "/nonexistent"}, home=Path(home)), str(binary))

    def test_last_resort_is_the_bare_name(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertIn(w.find_claude({"PATH": "/nonexistent"}, home=Path(home)), ("claude", "/usr/local/bin/claude"))


class RunClaudeTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_binary_is_a_failure_not_a_crash(self):
        outcome = await w.run_claude("oi", Path("."), 5, binary="/nonexistent/claude")
        self.assertFalse(outcome.ok)

    async def test_timeout_kills_the_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "claude"
            fake.write_text("#!/bin/sh\nsleep 30\n")
            fake.chmod(0o755)
            outcome = await w.run_claude("oi", Path(tmp), 0.3, binary=str(fake))
        self.assertEqual(outcome.status, w.TIMEOUT)


if __name__ == "__main__":
    unittest.main()
