"""Does a reminder about to be marked clash with one that is already pending?

A reminder knows when it starts and, if the user said so ("por 2 horas", "das 9 às 11"), how long it lasts.
Three kinds of clash, from the earlier of the two events:
  * "same"    — they start at the same minute;
  * "overlap" — the earlier one has a known duration and it runs past the start of the other;
  * "near"    — the earlier one has no known duration and the other starts within an hour of it
                (it may or may not fit: the bot asks "dá tempo dos dois?").
Repeating reminders are expanded over the next two weeks, so "toda segunda" clashes with a Monday one-off.
Stdlib only."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .reminder_text import human_minutes
from .reminders import Reminder
from .repeat import DAILY, WEEKDAYS_ONLY, WEEKLY, label
from .when import describe

NEAR = timedelta(minutes=60)
HORIZON = timedelta(days=14)
MAX_LISTED = 3


@dataclass(frozen=True)
class Slot:
    """Something that takes up time: a stored reminder, or the one about to be marked."""
    text: str
    start: datetime
    duration: int = 0  # minutes; 0 = unknown, a point in time
    repeat: str | None = None
    number: int | None = None  # the reminder id, when it is already stored

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.duration)


@dataclass(frozen=True)
class Conflict:
    other: Slot  # the one that is already there
    mine: Slot   # the new one (the occurrence that clashes)
    kind: str    # "same" | "overlap" | "near"


def slot_of(reminder: Reminder) -> Slot:
    return Slot(reminder.text, reminder.event or reminder.due, reminder.duration, reminder.repeat, reminder.id)


def occurrences(slot: Slot) -> list[Slot]:
    """The slot itself, or its repeats over the next two weeks."""
    if slot.repeat not in (DAILY, WEEKDAYS_ONLY, WEEKLY):
        return [slot]
    step = timedelta(days=7 if slot.repeat == WEEKLY else 1)
    found, start, limit = [], slot.start, slot.start + HORIZON
    while start <= limit:
        if not (slot.repeat == WEEKDAYS_ONLY and start.weekday() >= 5):
            found.append(Slot(slot.text, start, slot.duration, slot.repeat, slot.number))
        start += step
    return found


def clash(a: Slot, b: Slot) -> str | None:
    if a.start == b.start:
        return "same"
    first, second = (a, b) if a.start < b.start else (b, a)
    if first.duration:
        return "overlap" if first.end > second.start else None  # it ends before the other starts: it fits
    return "near" if second.start - first.start <= NEAR else None


def find_conflicts(pending: list[Reminder], mine: Slot) -> list[Conflict]:
    """Every stored reminder that clashes with `mine`, each once (its first clashing occurrence), earliest first."""
    found: list[Conflict] = []
    my_occurrences = occurrences(mine)
    for reminder in pending:
        other = slot_of(reminder)
        if other.text == mine.text and other.start == mine.start and other.repeat == mine.repeat:
            continue  # the very same reminder asked twice: the store already treats it as one
        for theirs in occurrences(other):
            hit = next(((m, clash(theirs, m)) for m in my_occurrences if clash(theirs, m)), None)
            if hit:
                found.append(Conflict(theirs, hit[0], hit[1]))
                break
    return sorted(found, key=lambda c: (c.mine.start, c.other.start))


def _body(text: str) -> str:
    return text.rstrip(" .!?;:,")


def _when(slot: Slot, now: datetime) -> str:
    return describe(slot.start, now)


def _line(c: Conflict, now: datetime) -> str:
    other, mine = c.other, c.mine
    name, new = f"“{_body(other.text)}”", f"“{_body(mine.text)}”"
    again = f" (repete {label(other.repeat, other.start)})" if other.repeat else ""
    if c.kind == "same":
        return f"{name}{again} já está marcado para {_when(other, now)}"
    if c.kind == "overlap":
        first_is_other = other.start < mine.start
        if first_is_other:
            return f"{name}{again} vai de {other.start:%H:%M} até {other.end:%H:%M} e {new} começa às {mine.start:%H:%M}"
        return f"{new} vai de {mine.start:%H:%M} até {mine.end:%H:%M} e {name}{again} começa às {other.start:%H:%M}"
    gap = human_minutes(round(abs((mine.start - other.start).total_seconds()) / 60))
    where = "antes" if other.start < mine.start else "depois"
    return f"{name}{again} é {_when(other, now)}, {gap} {where} de {new} ({mine.start:%H:%M})"


def question(conflicts: list[Conflict], now: datetime) -> str:
    """The question the bot asks instead of marking: what clashes, and whether to mark anyway."""
    listed = conflicts[:MAX_LISTED]
    if len(listed) == 1:
        c = listed[0]
        tail = {"same": "Marco o novo no mesmo horário?",
                "overlap": "Marco mesmo assim?",
                "near": "Dá tempo dos dois? Marco mesmo assim?"}[c.kind]
        return f"{_line(c, now)}, senhor. {tail} Se preferir, diga outro horário."
    lines = "\n".join(f"{i}. {_line(c, now)}" for i, c in enumerate(listed, 1))
    more = f"\n(+{len(conflicts) - len(listed)} mais)" if len(conflicts) > len(listed) else ""
    return f"Isso esbarra em outros compromissos, senhor:\n{lines}{more}\nMarco mesmo assim? Ou diga outro horário."
