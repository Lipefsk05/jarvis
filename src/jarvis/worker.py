"""The Worker: Claude Code in the background (`claude -p`), read-only, one job at a time.

The Talker answers right away; a request that needs real digging goes here. The job is stored,
runs in a subprocess with only Read/Grep/Glob and no user settings, and the answer comes back
through the outbox. `claude -p` runs on the Pro subscription quota (no pay-as-you-go), so the
daily number of jobs is capped. Stdlib only."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

QUEUED, RUNNING, DONE, FAILED, TIMEOUT, INTERRUPTED = "na fila", "rodando", "pronto", "falhou", "estourou o tempo", "interrompido"
OPEN = (QUEUED, RUNNING)
MAX_REQUEST_CHARS = 2000
MAX_RESULT_CHARS = 3500
MAX_QUEUE = 3
KEEP_JOBS = 50

BRIEFING = (
    "Você é o Trabalhador do Jarvis, assistente pessoal do Felipe. Seu cwd é o Mind dele (notas e tarefas em markdown). "
    "Você só pode ler (Read, Grep, Glob): não escreve nem executa nada. Responda em português, texto simples (sem "
    "markdown pesado), direto ao ponto, em até uns 1500 caracteres. Se faltar informação, diga o que faltou em vez de inventar."
)


class WorkerError(ValueError):
    """The request cannot be accepted. The message is user-safe."""


@dataclass
class Job:
    id: int
    request: str
    status: str
    created: datetime
    finished: datetime | None = None
    result: str = ""
    seconds: float = 0.0
    kind: str = "pedido"  # "pedido" (asked by the user, capped per day) or "resumo" (the daily digest)

    def to_json(self) -> dict:
        return {
            "id": self.id, "request": self.request, "status": self.status, "created": self.created.isoformat(),
            "finished": self.finished.isoformat() if self.finished else None, "result": self.result, "seconds": self.seconds,
            "kind": self.kind,
        }

    @staticmethod
    def from_json(raw: dict) -> "Job":
        finished = raw.get("finished")
        return Job(
            id=int(raw["id"]), request=str(raw["request"]), status=str(raw["status"]),
            created=datetime.fromisoformat(raw["created"]),
            finished=datetime.fromisoformat(finished) if finished else None,
            result=str(raw.get("result") or ""), seconds=float(raw.get("seconds") or 0),
            kind=str(raw.get("kind") or "pedido"),
        )


class JobStore:
    """Jobs in one JSON file, written atomically. A job left open by a restart is marked interrupted."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._next_id = 1
        self._items: dict[int, Job] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._items = {j.id: j for j in map(Job.from_json, data.get("jobs", []))}
            self._next_id = int(data.get("next_id", 1))
        except (OSError, ValueError, KeyError):
            log.exception("Could not read %s; starting with no jobs", self._path.name)
            return
        for job in self._items.values():
            if job.status in OPEN:
                job.status = INTERRUPTED
        self._next_id = max([self._next_id, *(i + 1 for i in self._items)])
        self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        keep = sorted(self._items)[-KEEP_JOBS:]
        payload = {"next_id": self._next_id, "jobs": [self._items[i].to_json() for i in keep]}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self._path)

    def add(self, request: str, now: datetime, kind: str = "pedido") -> Job:
        job = Job(self._next_id, request, QUEUED, now, kind=kind)
        self._next_id += 1
        self._items[job.id] = job
        self._save()
        return job

    def update(self, job: Job) -> None:
        self._items[job.id] = job
        self._save()

    def get(self, job_id: int) -> Job | None:
        return self._items.get(job_id)

    def open_jobs(self) -> list[Job]:
        return [j for j in self._items.values() if j.status in OPEN]

    def recent(self, limit: int = 5) -> list[Job]:
        return [self._items[i] for i in sorted(self._items)[-limit:]][::-1]

    def started_on(self, day: date) -> int:
        """Jobs created that day, whatever happened to them (they all spent, or tried to spend, quota)."""
        return sum(1 for j in self._items.values() if j.kind == "pedido" and j.created.date() == day)


@dataclass(frozen=True)
class Outcome:
    ok: bool
    text: str  # the answer, or a user-safe reason when not ok
    status: str = DONE


Runner = Callable[..., Awaitable[Outcome]]  # (request, cwd, timeout) and, for digests, tools=""


async def run_claude(request: str, cwd: Path, timeout_s: float, binary: str = "claude", tools: str = "Read,Grep,Glob") -> Outcome:
    """One `claude -p` call: read-only tools (none when `tools` is empty), no user/project settings (small context),
    no session saved. The request goes through stdin, never through the command line."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}  # the subscription pays, never a stray key
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, "-p", "--output-format", "json", "--tools", tools, "--setting-sources", "",
            "--no-session-persistence", "--permission-mode", "dontAsk", "--append-system-prompt", BRIEFING,
            cwd=str(cwd), env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return Outcome(False, f"não consegui iniciar o Claude Code ({type(exc).__name__})", FAILED)
    try:
        out, err = await asyncio.wait_for(proc.communicate(request.encode("utf-8")), timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return Outcome(False, f"passou de {int(timeout_s // 60)} min e eu interrompi", TIMEOUT)
    return parse_output(proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))


def parse_output(code: int, out: str, err: str) -> Outcome:
    """Turn the JSON `claude -p` printed into an outcome. Never raises on odd output."""
    try:
        data = json.loads(out)
    except ValueError:
        data = None
    if isinstance(data, dict) and not data.get("is_error") and isinstance(data.get("result"), str) and data["result"].strip():
        return Outcome(True, data["result"].strip())
    detail = ""
    if isinstance(data, dict) and isinstance(data.get("result"), str):
        detail = data["result"]
    detail = detail or err
    if re.search(r"oauth|login|authenticat|expired", detail, re.IGNORECASE):
        return Outcome(False, "o login do Claude Code expirou (rode `claude auth login`)", FAILED)
    if re.search(r"rate.?limit|usage limit|quota|limit reached", detail, re.IGNORECASE):
        return Outcome(False, "a cota da assinatura acabou por agora", FAILED)
    return Outcome(False, f"o Claude Code terminou sem resposta (código {code})", FAILED)


class Worker:
    """Takes requests, runs them one at a time and hands each finished text to `deliver`."""

    def __init__(
        self,
        store: JobStore,
        cwd: Path,
        deliver: Callable[[str], Awaitable[bool]],
        clock: Callable[[], datetime],
        *,
        timeout_s: float = 300.0,
        daily_max: int = 10,
        runner: Runner | None = None,
    ) -> None:
        self._store = store
        self._cwd = cwd
        self._deliver = deliver
        self._clock = clock
        self._timeout = timeout_s
        self._daily_max = daily_max
        self._runner = runner or run_claude
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._digests: dict[int, str] = {}  # job id -> prompt kept in memory only: it holds the text of the mails

    def submit(self, request: str) -> Job:
        """Queue a request or raise WorkerError saying why not."""
        request = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]+", " ", request).strip()[:MAX_REQUEST_CHARS]
        if not request:
            raise WorkerError("O que devo pedir ao Trabalhador, senhor? Use /pede <pedido>.")
        if len(self._store.open_jobs()) >= MAX_QUEUE:
            raise WorkerError("O Trabalhador já tem pedidos demais na fila, senhor. Espero um terminar.")
        if self._store.started_on(self._clock().date()) >= self._daily_max:
            raise WorkerError(f"Já fiz {self._daily_max} pedidos ao Trabalhador hoje, senhor; cada um gasta a cota da assinatura. Amanhã há mais.")
        job = self._store.add(request, self._clock())
        self._queue.put_nowait(job.id)
        return job

    def submit_digest(self, label: str, prompt: str) -> Job:
        """Queue a digest (no tools, outside the daily cap). The prompt is never written to disk."""
        job = self._store.add(label, self._clock(), kind="resumo")
        self._digests[job.id] = prompt
        self._queue.put_nowait(job.id)
        return job

    async def run(self) -> None:
        """The loop: one job at a time, for as long as the bot lives."""
        while True:
            job = self._store.get(await self._queue.get())
            if job is None or job.status != QUEUED:
                continue
            try:
                await self._work(job)
            except Exception:  # one bad job must not stop the loop
                log.exception("Job %s crashed", job.id)

    async def _work(self, job: Job) -> None:
        job.status = RUNNING
        self._store.update(job)
        started = self._clock()
        try:
            prompt = self._digests.pop(job.id, None)
            if prompt is None:
                outcome = await self._runner(job.request, self._cwd, self._timeout)
            else:
                outcome = await self._runner(prompt, self._cwd, self._timeout, tools="")
        except Exception as exc:
            log.exception("Job %s failed", job.id)
            outcome = Outcome(False, f"falha inesperada ({type(exc).__name__})", FAILED)
        job.status = outcome.status if not outcome.ok else DONE
        job.result = outcome.text[:MAX_RESULT_CHARS]
        job.finished = self._clock()
        job.seconds = (job.finished - started).total_seconds()
        self._store.update(job)
        await self._deliver(format_delivery(job))


def format_delivery(job: Job) -> str:
    if job.kind == "resumo":
        return f"{job.request}, senhor:\n\n{job.result}" if job.status == DONE else f"Não consegui montar o resumo ({job.request}): {job.result}."
    if job.status == DONE:
        return f"Trabalhador, pedido {job.id} pronto, senhor:\n\n{job.result}"
    return f"O pedido {job.id} ao Trabalhador não deu certo, senhor: {job.result}."


def listing(jobs: list[Job]) -> str:
    if not jobs:
        return "Nenhum pedido ao Trabalhador ainda, senhor."
    lines = ["Pedidos ao Trabalhador:"]
    for job in jobs:
        request = job.request if len(job.request) <= 60 else job.request[:57] + "…"
        lines.append(f"{job.id}. {job.status} — {request}")
    return "\n".join(lines)
