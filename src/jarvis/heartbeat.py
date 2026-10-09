"""Liveness heartbeat: one timestamp file, overwritten every minute, so a restart can tell
how long the bot was down. The file never grows."""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 60
MIN_GAP = timedelta(minutes=10)  # smaller gaps are plain restarts, not worth reporting


@dataclass(frozen=True)
class Outage:
    start: datetime
    end: datetime

    def describe(self) -> str:
        same_day = self.start.date() == self.end.date()
        start = f"{self.start:%H:%M}" if same_day else f"{self.start:%d/%m %H:%M}"
        return f"das {start} às {self.end:%H:%M}" if same_day else f"de {start} até {self.end:%d/%m %H:%M}"


def read_last(path: Path) -> datetime | None:
    try:
        return datetime.fromisoformat(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def write_beat(path: Path, now: datetime) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(now.isoformat(), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        log.warning("Could not write the heartbeat file %s", path)


def find_outage(last: datetime | None, now: datetime) -> Outage | None:
    """The gap between the last beat and now, if it is long enough to matter."""
    if last is None or now - last < MIN_GAP:
        return None
    return Outage(last, now)


async def run(path: Path, clock) -> None:
    while True:
        write_beat(path, clock())
        await asyncio.sleep(INTERVAL_SECONDS)
