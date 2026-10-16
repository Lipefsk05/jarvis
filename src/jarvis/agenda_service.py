"""The agenda as the bot uses it: read every account, create, move and delete (blocking calls; the bot runs
them in a thread). One account failing never hides the others: it is reported next to what could be read."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from .agenda import Account, Shown, merge, overlapping, parse_ref, search
from .agenda_flow import Plan
from .gcal import CalendarError, Event, GoogleCalendar

SEARCH_DAYS = 60


@dataclass(frozen=True)
class Reading:
    items: list[Shown]
    failed: list[Account]


class Agenda:
    def __init__(self, calendar: GoogleCalendar, accounts: tuple[Account, ...], clock: Callable[[], datetime]) -> None:
        self._calendar = calendar
        self.accounts = accounts
        self._clock = clock

    def read(self, start: datetime, end: datetime) -> Reading:
        per_account, failed = [], []
        for account in self.accounts:
            try:
                per_account.append((account, self._calendar.list_events(account.calendar, start, end)))
            except CalendarError:
                failed.append(account)
        return Reading(merge(per_account), failed)

    def clashes(self, plan: Plan) -> Reading:
        """What already sits in the slot of a new event, in any account (the owner sees them as one calendar)."""
        reading = self.read(plan.start, plan.end)
        return Reading(overlapping(reading.items, plan.start, plan.end), reading.failed)

    def create(self, plan: Plan, event_id: str | None = None) -> Event:
        return self._calendar.insert(plan.account.calendar, plan.title, plan.start, plan.end, event_id=event_id)

    def find(self, words: str) -> Reading:
        """Upcoming events (next 60 days) whose title has the owner's words."""
        now = self._clock()
        reading = self.read(now, now + timedelta(days=SEARCH_DAYS))
        return Reading(search(reading.items, words), reading.failed)

    def move(self, ref: str, start: datetime, end: datetime) -> list[Account]:
        """Move every copy of the event. Returns the accounts that could not be changed."""
        failed = []
        for account, event_id in parse_ref(ref, self.accounts):
            try:
                self._calendar.move(account.calendar, event_id, start, end)
            except CalendarError:
                failed.append(account)
        return failed

    def delete(self, ref: str) -> list[Account]:
        failed = []
        for account, event_id in parse_ref(ref, self.accounts):
            try:
                self._calendar.delete(account.calendar, event_id)
            except CalendarError:
                failed.append(account)
        return failed
