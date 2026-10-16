"""The day's tasks, mirrored into one separate Google calendar as all-day items (one way: the plan writes, the
calendar only shows; anything edited there is put back at the next sync).

One item per task. It sits on the day the plan gives it, reads "✓ title" once done, moves to the next day when it
slips, and disappears when the task leaves the plan (gone from the board, skipped or pushed out). Items of days
already gone stay as a record. Ids come from the task's id, so syncing twice never duplicates anything."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .gcal import CalendarError, GoogleCalendar
from .plan import DONE, PLANNED, HORIZON_DAYS, KEEP_DAYS, PlanStore

log = logging.getLogger(__name__)

ID_PREFIX = "jvt"
DONE_MARK = "✓ "


def event_id(task_id: str) -> str:
    """A stable calendar id for a task: lowercase hex, which Google accepts, so the same task is always the same item."""
    return ID_PREFIX + hashlib.sha1(task_id.encode("utf-8")).hexdigest()[:30]


@dataclass(frozen=True)
class Wanted:
    day: date
    title: str
    description: str


def wanted(store: PlanStore, today: date) -> dict[str, Wanted]:
    """What the calendar should show: from today on, every task that is planned or done, once, on its latest day.
    Done tasks of today stay (as ✓); older days are not part of this, they are history."""
    found: dict[str, Wanted] = {}
    for plan in store.days():
        if plan.day < today or plan.day > today + timedelta(days=HORIZON_DAYS):
            continue
        for item in plan.items:
            if item.status not in (PLANNED, DONE):
                continue
            title = (DONE_MARK if item.status == DONE else "") + item.title
            found[event_id(item.task_id)] = Wanted(plan.day, title, item.area)
    return found


class TaskCalendar:
    def __init__(self, calendar: GoogleCalendar, calendar_id: str, zone) -> None:
        self._calendar, self._id, self._zone = calendar, calendar_id, zone

    def sync(self, store: PlanStore, today: date) -> tuple[int, int]:
        """Bring the calendar to what the plan says. Returns (written, deleted). Raises CalendarError."""
        start = datetime.combine(today - timedelta(days=KEEP_DAYS), time.min, tzinfo=self._zone)
        end = datetime.combine(today + timedelta(days=HORIZON_DAYS + 2), time.min, tzinfo=self._zone)
        existing = {e.id: e for e in self._calendar.list_events(self._id, start, end) if e.id.startswith(ID_PREFIX)}
        goal = wanted(store, today)
        written = deleted = 0
        for key, want in goal.items():
            have = existing.get(key)
            if have is not None and have.title == want.title and have.start.date() == want.day:
                continue
            self._calendar.upsert_all_day(self._id, key, want.title, want.day, want.description)
            written += 1
        for key, have in existing.items():
            if key in goal or have.start.date() < today:
                continue  # wanted, or a day already gone (a record)
            self._calendar.delete(self._id, key)
            deleted += 1
        return written, deleted


def safe_sync(tasks: TaskCalendar, store: PlanStore, today: date) -> None:
    """Never let the calendar break the plan: a failure is logged and tried again at the next change."""
    try:
        written, deleted = tasks.sync(store, today)
        if written or deleted:
            log.info("Task calendar synced: %d written, %d removed", written, deleted)
    except CalendarError as exc:
        log.warning("Task calendar not synced: %s", exc)
