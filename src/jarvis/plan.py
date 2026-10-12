"""Daily plan model: the day as elastic blocks anchored on what actually happened, plus the plan file.

The Felipe's day moves (he arrives at work between ~9h and ~10h30, rides a bus 40-60 min each way), so
nothing is a fixed clock time. Four anchors move everything: leaving home, arriving at work, leaving work,
arriving home. Told anchors win; missing ones are estimated from habits (arrival defaults to the *end* of the
usual range, so nothing is planned over time he may still be away). This module only models and stores;
choosing which task goes where is the planner's job. Saturday daytime is sacred (see vida-pessoal/rotina.md);
the Friday sunset edge is not modeled yet, only the day-level capacity of 0.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

# Where a block happens
HOME, BUS, WORK = "casa", "onibus", "trabalho"
# What a task needs (where it can be done)
NOTEBOOK, PHONE, ANY = "notebook", "celular", "qualquer"
# Plan item status
PLANNED, DONE, POSTPONED, SKIPPED = "planejado", "feito", "adiado", "pulado"
STATUSES = (PLANNED, DONE, POSTPONED, SKIPPED)
ANCHORS = ("leave_home", "arrive_work", "leave_work", "arrive_home")  # saída de casa, chegada ao trabalho, saída do trabalho, chegada em casa
SABBATH_WEEKDAY = 5  # Saturday (Monday is 0)
KEEP_DAYS = 14
MAX_TITLE_CHARS = 200


@dataclass(frozen=True)
class Habits:
    """Defaults used when an anchor was not told. All adjustable; learned values replace them later."""
    arrive_work: time = time(10, 30)      # end of the usual 9:00-10:30 range, never the early end
    work_minutes: int = 6 * 60            # internship; 8-9 h if it becomes CLT
    bus_minutes: int = 50                 # 40 min to 1 h each way
    wake: time = time(7, 0)
    evening_end: time = time(22, 0)
    capacity_weekday: int = 3             # starts low; grows as the Felipe sees it work
    capacity_weekend: int = 2

    def capacity(self, day: date) -> int:
        if day.weekday() == SABBATH_WEEKDAY:
            return 0
        return self.capacity_weekend if day.weekday() >= 5 else self.capacity_weekday


@dataclass(frozen=True)
class Block:
    kind: str            # "casa_manha" | "onibus_ida" | "trabalho" | "onibus_volta" | "casa_noite"
    place: str           # HOME | BUS | WORK
    start: datetime
    end: datetime
    estimated: bool      # some edge was guessed, so the block may shift; the plan treats it as "if it fits"

    @property
    def minutes(self) -> int:
        return max(0, int((self.end - self.start).total_seconds() // 60))

    def accepts(self, needs: str) -> bool:
        """Whether a task needing `needs` can be done here. The bus is phone-only; at work only if
        the load allows, so the planner must treat WORK as a last, "if possible" slot."""
        if self.place == HOME:
            return True
        return needs in (PHONE, ANY)


def resolve_anchors(day: date, told: dict[str, datetime], habits: Habits, tz) -> tuple[dict, dict]:
    """The four anchors for `day`, as (moments, estimated flags). Guesses grow outward from the first told
    anchor (or from the usual arrival, if nothing was told) and never contradict a told one: a guess that
    would land after a later told anchor is pulled earlier, but never closer than the bus ride to the one before."""
    for name in told:
        if name not in ANCHORS:
            raise ValueError(f"unknown anchor {name!r}")
    bus, work = timedelta(minutes=habits.bus_minutes), timedelta(minutes=habits.work_minutes)
    gap = {"arrive_work": bus, "leave_work": work, "arrive_home": bus}  # time since the previous anchor
    estimated = {name: name not in told for name in ANCHORS}
    told_times = [told[n] for n in ANCHORS if n in told]
    if told_times != sorted(told_times):
        raise ValueError("anchors out of order")
    start = next((i for i, n in enumerate(ANCHORS) if n in told), 1)
    moments = {ANCHORS[start]: told.get(ANCHORS[start]) or datetime.combine(day, habits.arrive_work, tz)}
    for i in range(start - 1, -1, -1):
        moments[ANCHORS[i]] = moments[ANCHORS[i + 1]] - gap[ANCHORS[i + 1]]
    for i in range(start + 1, len(ANCHORS)):
        moments[ANCHORS[i]] = told.get(ANCHORS[i]) or moments[ANCHORS[i - 1]] + gap[ANCHORS[i]]
    for i in range(len(ANCHORS) - 2, -1, -1):
        name, following = ANCHORS[i], ANCHORS[i + 1]
        if estimated[name]:
            moments[name] = min(moments[name], moments[following] - gap[following])
    floor = {"arrive_work": bus, "leave_work": timedelta(0), "arrive_home": bus}  # shortest plausible gap
    for i in range(1, len(ANCHORS)):  # told anchors can squeeze a guess, but never into the past of the one before
        name = ANCHORS[i]
        if estimated[name]:
            moments[name] = max(moments[name], moments[ANCHORS[i - 1]] + floor[name])
    return {n: moments[n] for n in ANCHORS}, estimated


def build_blocks(day: date, told: dict[str, datetime], habits: Habits, tz) -> list[Block]:
    """The five blocks of a work day, in order, anchored on what was told."""
    moments, estimated = resolve_anchors(day, told, habits, tz)
    leave_home, arrive = moments["leave_home"], moments["arrive_work"]
    leave, home = moments["leave_work"], moments["arrive_home"]
    morning_start = datetime.combine(day, habits.wake, tz)
    evening_end = max(datetime.combine(day, habits.evening_end, tz), home)
    return [
        Block("casa_manha", HOME, min(morning_start, leave_home), leave_home, True),
        Block("onibus_ida", BUS, leave_home, arrive, estimated["leave_home"] or estimated["arrive_work"]),
        Block("trabalho", WORK, arrive, leave, estimated["arrive_work"] or estimated["leave_work"]),
        Block("onibus_volta", BUS, leave, home, estimated["leave_work"] or estimated["arrive_home"]),
        Block("casa_noite", HOME, home, evening_end, estimated["arrive_home"]),
    ]


@dataclass
class PlanItem:
    task_id: str          # the board's ^id when it has one, else a stable key made by the planner
    title: str
    needs: str = ANY      # NOTEBOOK | PHONE | ANY
    block: str = ""       # Block.kind it was placed in; "" = not placed yet
    status: str = PLANNED
    minutes: int = 0      # 0 = unknown size

    def __post_init__(self) -> None:
        if self.needs not in (NOTEBOOK, PHONE, ANY):
            raise ValueError(f"unknown need {self.needs!r}")
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        self.title = " ".join(self.title.split())[:MAX_TITLE_CHARS]
        self.minutes = max(0, int(self.minutes))

    def to_json(self) -> dict:
        return {"task_id": self.task_id, "title": self.title, "needs": self.needs, "block": self.block,
                "status": self.status, "minutes": self.minutes}

    @staticmethod
    def from_json(raw: dict) -> "PlanItem":
        return PlanItem(str(raw["task_id"]), str(raw["title"]), raw.get("needs", ANY), raw.get("block", ""),
                        raw.get("status", PLANNED), int(raw.get("minutes") or 0))


@dataclass
class DayPlan:
    day: date
    told: dict[str, datetime] = field(default_factory=dict)   # anchors the Felipe reported
    items: list[PlanItem] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"day": self.day.isoformat(), "told": {k: v.isoformat() for k, v in self.told.items()},
                "items": [i.to_json() for i in self.items]}

    @staticmethod
    def from_json(raw: dict) -> "DayPlan":
        return DayPlan(date.fromisoformat(raw["day"]),
                       {k: datetime.fromisoformat(v) for k, v in raw.get("told", {}).items()},
                       [PlanItem.from_json(i) for i in raw.get("items", [])])

    def open_items(self) -> list[PlanItem]:
        return [i for i in self.items if i.status == PLANNED]


class PlanStore:
    """One JSON file, a plan per day, written atomically. Corrupt files are set aside, never overwritten."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._days: dict[date, DayPlan] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            plans = [DayPlan.from_json(p) for p in raw["days"]]
            self._days = {p.day: p for p in plans}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            quarantine = self._path.with_suffix(".corrupt")
            log.warning("Could not read the plan at %s; moved to %s and starting empty", self._path, quarantine)
            try:
                os.replace(self._path, quarantine)
            except OSError:
                pass
            self._days = {}

    def _save(self, today: date) -> None:
        cutoff = today - timedelta(days=KEEP_DAYS)
        self._days = {d: p for d, p in self._days.items() if d >= cutoff}
        payload = {"days": [p.to_json() for _, p in sorted(self._days.items())]}
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

    def put(self, plan: DayPlan) -> None:
        self._days[plan.day] = plan
        self._save(plan.day)

    def tell(self, day: date, anchor: str, moment: datetime, habits: Habits, tz) -> DayPlan:
        """Record a reported anchor ("cheguei", "saí", "cheguei em casa") and keep the day consistent.
        Raises ValueError if it contradicts anchors already told (e.g. leaving before arriving)."""
        if moment.tzinfo is None:
            raise ValueError("moment must be timezone-aware")
        plan = self._days.get(day) or DayPlan(day)
        candidate = {**plan.told, anchor: moment}
        resolve_anchors(day, candidate, habits, tz)  # validates name and order
        plan.told = candidate
        self.put(plan)
        return plan

    def mark(self, day: date, task_id: str, status: str) -> PlanItem | None:
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        plan = self._days.get(day)
        item = next((i for i in plan.items if i.task_id == task_id), None) if plan else None
        if item is None:
            return None
        item.status = status
        self.put(plan)
        return item
