"""Wakes up often, finds reminders that are due and delivers them through the outbox.

Delay policy: on time (within GRACE) -> one message, closed as sent. Late (bot was down) ->
everything late goes in ONE message, closed as late. Older than EXPIRES -> not sent as a
fresh reminder; it is listed once in the late message and closed as lost. A reminder is only
closed after its message was really delivered, so a failed send is retried on the next tick."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from .outbox import Outbox
from .reminder_text import ReminderVoice
from .reminders import LATE, LOST, SENT, Reminder, ReminderStore

log = logging.getLogger(__name__)

TICK_SECONDS = 30
GRACE = timedelta(minutes=2)  # a normal tick or a quick restart is under this; more is worth saying
EXPIRES = timedelta(hours=24)


@dataclass
class Plan:
    on_time: list[Reminder] = field(default_factory=list)
    late: list[Reminder] = field(default_factory=list)
    lost: list[Reminder] = field(default_factory=list)


def plan(due: list[Reminder], now: datetime) -> Plan:
    result = Plan()
    for r in due:
        lateness = now - r.due
        if lateness <= GRACE:
            result.on_time.append(r)
        elif lateness <= EXPIRES:
            result.late.append(r)
        else:
            result.lost.append(r)
    return result


async def run_once(
    store: ReminderStore,
    outbox: Outbox,
    voice: ReminderVoice,
    now: datetime,
    on_delivered: Callable[[str], None] | None = None,
) -> int:
    """Deliver everything due at `now`. Returns how many reminders were closed."""
    todo = plan(store.due(now), now)
    closed = 0

    async def send(text: str, items: list[Reminder], statuses: list[str]) -> None:
        nonlocal closed
        if await outbox.deliver(text):
            for item, status in zip(items, statuses):
                store.close(item.id, status, now)
            closed += len(items)
            if on_delivered:
                on_delivered(text)

    if todo.on_time:
        await send(voice.on_time(todo.on_time, now), todo.on_time, [SENT] * len(todo.on_time))
    if todo.late or todo.lost:
        await send(
            voice.late(todo.late, todo.lost, now),
            todo.late + todo.lost,
            [LATE] * len(todo.late) + [LOST] * len(todo.lost),
        )
    return closed


async def run(
    store: ReminderStore,
    outbox: Outbox,
    clock: Callable[[], datetime],
    on_delivered: Callable[[str], None] | None = None,
    voice: ReminderVoice | None = None,
) -> None:
    voice = voice or ReminderVoice()
    while True:
        try:
            await run_once(store, outbox, voice, clock(), on_delivered)
        except Exception:  # the loop must outlive any single bad tick
            log.exception("Reminder tick failed")
        await asyncio.sleep(TICK_SECONDS)
