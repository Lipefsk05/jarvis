"""Daily plan model: which tasks belong to which day, how many a day holds, and the plan file.

The plan is a calendar of tasks for the next month. There are no clock times and nothing to report during the
day: the Felipe says "concluí X" when he finishes something, and once a day (midnight, or when the bot starts
if the PC was off) the planner settles the days that passed and refills the ones ahead. What was not done rolls
to the next day. How many tasks a day holds (`Load`) starts low and follows what he really delivers: a couple
of full days in a row raise it, a couple of short days lower it. Saturday daytime is sacred (see
vida-pessoal/rotina.md): capacity 0. This module only models and stores; choosing the tasks is the planner's job.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

# What a task needs (where it can be done); informational, shown next to the task
NOTEBOOK, PHONE, ANY = "notebook", "celular", "qualquer"
# Plan item status
PLANNED, DONE, POSTPONED, SKIPPED = "planejado", "feito", "adiado", "pulado"
STATUSES = (PLANNED, DONE, POSTPONED, SKIPPED)
SABBATH_WEEKDAY = 5  # Saturday (Monday is 0)
HORIZON_DAYS = 30    # the plan always looks a month ahead
KEEP_DAYS = 14       # days already gone that stay in the file
MAX_TITLE_CHARS = 200

BASE_CAPACITY = 3    # tasks in a weekday at first; Sunday holds one less
MIN_CAPACITY, MAX_CAPACITY = 1, 8
MAX_FIXED = 10      # the ceiling of a capacity the Felipe sets by hand (/capacidade)
STREAK_DAYS = 2      # days in a row (all done / some left) before the capacity moves by one


@dataclass
class Load:
    """How much a day holds, learned from what was delivered. `settled` is the last day already judged."""
    base: int = BASE_CAPACITY
    full: int = 0                   # days in a row with every planned task done
    short: int = 0                  # days in a row with something left over
    settled: date | None = None
    rebalanced: date | None = None  # the day the planner last refilled the calendar
    fixed: int | None = None        # set by hand (/capacidade): the day holds exactly this, and nothing is learned

    def capacity(self, day: date) -> int:
        if day.weekday() == SABBATH_WEEKDAY:
            return 0
        size = self.base if self.fixed is None else self.fixed
        return max(MIN_CAPACITY, size - 1) if day.weekday() == 6 else size

    def record(self, day: date, delivered_all: bool) -> None:
        """Judge one finished day (sabbath excluded by the caller) and move the capacity if the streak is long enough."""
        if self.fixed is not None:
            return  # a number chosen by hand is not second-guessed: a day with something left over teaches nothing
        if delivered_all:
            self.full, self.short = self.full + 1, 0
        else:
            self.short, self.full = self.short + 1, 0
        if self.full >= STREAK_DAYS:
            self.base, self.full = min(MAX_CAPACITY, self.base + 1), 0
        elif self.short >= STREAK_DAYS:
            self.base, self.short = max(MIN_CAPACITY, self.base - 1), 0

    def to_json(self) -> dict:
        return {"base": self.base, "full": self.full, "short": self.short,
                "settled": self.settled.isoformat() if self.settled else None,
                "rebalanced": self.rebalanced.isoformat() if self.rebalanced else None, "fixed": self.fixed}

    @staticmethod
    def from_json(raw: dict) -> "Load":
        def when(key: str) -> date | None:
            return date.fromisoformat(raw[key]) if raw.get(key) else None
        base = int(raw.get("base", BASE_CAPACITY))
        fixed = raw.get("fixed")
        return Load(min(MAX_CAPACITY, max(MIN_CAPACITY, base)), max(0, int(raw.get("full", 0))),
                    max(0, int(raw.get("short", 0))), when("settled"), when("rebalanced"),
                    None if fixed is None else min(MAX_FIXED, max(MIN_CAPACITY, int(fixed))))


@dataclass
class PlanItem:
    task_id: str          # the board's ^id when it has one, else a stable key made by the board reader
    title: str
    needs: str = ANY      # NOTEBOOK | PHONE | ANY
    status: str = PLANNED
    minutes: int = 0      # 0 = unknown size
    area: str = ""        # "group/area" of the board file, to spread the day over projects and to name it in the inbox

    def __post_init__(self) -> None:
        if self.needs not in (NOTEBOOK, PHONE, ANY):
            raise ValueError(f"unknown need {self.needs!r}")
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        self.title = " ".join(self.title.split())[:MAX_TITLE_CHARS]
        self.minutes = max(0, int(self.minutes))

    def to_json(self) -> dict:
        return {"task_id": self.task_id, "title": self.title, "needs": self.needs, "status": self.status,
                "minutes": self.minutes, "area": self.area}

    @staticmethod
    def from_json(raw: dict) -> "PlanItem":  # old files carried "block"/"maybe"; they are ignored
        return PlanItem(str(raw["task_id"]), str(raw["title"]), raw.get("needs", ANY), raw.get("status", PLANNED),
                        int(raw.get("minutes") or 0), str(raw.get("area", "")))


@dataclass
class DayPlan:
    day: date
    items: list[PlanItem] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"day": self.day.isoformat(), "items": [i.to_json() for i in self.items]}

    @staticmethod
    def from_json(raw: dict) -> "DayPlan":  # old files carried "told" (anchors); ignored
        return DayPlan(date.fromisoformat(raw["day"]), [PlanItem.from_json(i) for i in raw.get("items", [])])

    def open_items(self) -> list[PlanItem]:
        return [i for i in self.items if i.status == PLANNED]

    def counted(self) -> list[PlanItem]:
        """What counts toward the day's capacity: everything that was not skipped."""
        return [i for i in self.items if i.status != SKIPPED]


class PlanStore:
    """One JSON file: a plan per day plus the learned load, written atomically. Corrupt files are set aside, never overwritten."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._days: dict[date, DayPlan] = {}
        self.load = Load()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            plans = [DayPlan.from_json(p) for p in raw["days"]]
            self._days = {p.day: p for p in plans}
            self.load = Load.from_json(raw.get("load") or {})
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            quarantine = self._path.with_suffix(".corrupt")
            log.warning("Could not read the plan at %s; moved to %s and starting empty", self._path, quarantine)
            try:
                os.replace(self._path, quarantine)
            except OSError:
                pass
            self._days, self.load = {}, Load()

    def save(self, today: date) -> None:
        cutoff = today - timedelta(days=KEEP_DAYS)
        self._days = {d: p for d, p in self._days.items() if d >= cutoff}
        payload = {"days": [p.to_json() for _, p in sorted(self._days.items())], "load": self.load.to_json()}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp, self._path)
        except OSError:
            log.warning("Could not save the plan to %s", self._path)

    def get(self, day: date) -> DayPlan | None:
        return self._days.get(day)

    def days(self) -> list[DayPlan]:
        return [p for _, p in sorted(self._days.items())]

    def put(self, plan: DayPlan, today: date | None = None) -> None:
        self._days[plan.day] = plan
        self.save(today or plan.day)

    def drop_after(self, day: date) -> None:
        """Forget every plan after `day` (the future is recomputed); the caller saves."""
        self._days = {d: p for d, p in self._days.items() if d <= day}

    def mark(self, day: date, task_id: str, status: str) -> PlanItem | None:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        plan = self._days.get(day)
        item = next((i for i in plan.items if i.task_id == task_id), None) if plan else None
        if item is None:
            return None
        item.status = status
        self.save(day)
        return item
