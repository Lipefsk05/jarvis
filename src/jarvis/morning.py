"""The morning summary ("resumão"): one message with the weather, the agenda, today's reminders, the plan and
the e-mail summaries. The code gathers every section; a section that fails is left out (and said), never the
whole message. The e-mail summaries come from the Worker and are awaited, so it all arrives as one message."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from .digest import Digest
from .tone import period_greeting
from .worker import DONE, Worker

log = logging.getLogger(__name__)

CHECK_SECONDS = 300
WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")

# A provider returns the text of its section, or None when there is nothing to say; it may raise.
Provider = Callable[[], Awaitable[str | None]]


def compose(now: datetime, sections: list[tuple[str, str]], failed: list[str]) -> str:
    """`sections` is (title, body); a body already starting with the title is not repeated."""
    lines = [f"{period_greeting(now)}, senhor. Resumo de {WEEKDAYS[now.weekday()]}, {now:%d/%m}:"]
    for title, body in sections:
        lines += ["", body if body.lower().startswith(title.lower()) else f"{title}\n{body}"]
    if failed:
        lines += ["", "Não consegui trazer: " + ", ".join(failed) + "."]
    return "\n".join(lines)


class Morning:
    def __init__(
        self,
        providers: list[tuple[str, Provider]],
        digest: Digest | None,
        worker: Worker,
        deliver: Callable[[str], Awaitable[bool]],
        clock: Callable[[], datetime],
        state_path: Path,
        hour: int = 7,
        mail_wait_s: float = 420.0,
    ) -> None:
        self._providers, self._digest, self._worker, self._deliver = providers, digest, worker, deliver
        self._clock, self._path, self._hour, self._mail_wait = clock, state_path, hour, mail_wait_s

    def _last_day(self) -> str | None:
        try:
            return json.loads(self._path.read_text(encoding="utf-8")).get("day")
        except (OSError, ValueError):
            return None

    def _mark(self, now: datetime) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"day": now.date().isoformat()}), encoding="utf-8")
        os.replace(tmp, self._path)

    def due(self) -> bool:
        now = self._clock()
        return now.hour >= self._hour and self._last_day() != now.date().isoformat()

    async def _mail_sections(self, failed: list[str]) -> list[tuple[str, str]]:
        if self._digest is None:
            return []
        prepared, notes, complete = await self._digest.gather(self._digest.cutoff())
        if not complete:
            failed.append("e-mail")
        jobs = [self._worker.submit_digest(label, prompt, silent=True) for label, prompt in prepared]
        sections = [("E-mails", note) for note in notes if "Não consegui" not in note]
        for job in await self._worker.wait([j.id for j in jobs], self._mail_wait):
            label = job.request.split("—", 1)[-1].strip()
            if job.status == DONE:
                sections.append((f"E-mails — {label}", job.result))
            else:
                failed.append(f"e-mails {label}")
        if complete:
            self._digest.mark()
        return sections

    async def build(self) -> str:
        now = self._clock()
        sections: list[tuple[str, str]] = []
        failed: list[str] = []
        for title, provider in self._providers:
            try:
                body = await provider()
            except Exception as exc:  # one source down must not cost the rest of the summary
                log.warning("Morning section %s failed: %s", title, type(exc).__name__)
                failed.append(title.lower())
                continue
            if body:
                sections.append((title, body))
        sections += await self._mail_sections(failed)
        return compose(now, sections, failed)

    async def run(self) -> bool:
        """Build and deliver the summary now. Marks the day done only when it really went out."""
        text = await self.build()
        delivered = await self._deliver(text)
        if delivered:
            self._mark(self._clock())
        return delivered

    async def loop(self) -> None:
        while True:
            try:
                if self.due():
                    await self.run()
            except Exception:
                log.exception("Morning summary tick failed")
            await asyncio.sleep(CHECK_SECONDS)
