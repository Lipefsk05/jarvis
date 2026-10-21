"""Chooses which tasks go on which day: board buckets + the learned load -> a month of DayPlans. Pure code, no model.

Order of choice: tasks that slipped from the last days first, then the `prioridade` bucket (deadline, then 🔴), then
the `lista` by priority; ideas never. Today's plan is stable once the day started (it is what the Felipe is working on): it only loses
what left the board and is topped up to the day's capacity; the first look at a new day builds it afresh. Every later day is recomputed from the pool, so the
forecast follows the board. At midnight (`rebalance`) the days that passed are judged: a task still open on the
board rolls on, and the learned capacity moves (see `plan.Load`).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import date, timedelta

from .board import BoardTask, HIGH, LOW, MEDIUM, blocked, split
from .plan import DONE, HORIZON_DAYS, PLANNED, POSTPONED, SKIPPED, DayPlan, PlanItem, PlanStore
from .textutil import fold

MAX_PER_AREA = 2  # no day made only of one project
_RANK = {HIGH: 0, MEDIUM: 1, LOW: 2}


def _candidates(tasks: list[BoardTask], today: date, carry: set[str]) -> list[BoardTask]:
    """Plannable tasks in the order they should be tried."""
    top = [t for t in tasks if t.depth == 0]
    buckets = split(top, today)
    rest = sorted((t for t in buckets["lista"] if not t.waits),
                  key=lambda t: (_RANK.get(t.priority, 3), t.due or date.max, t.title))
    open_ids = {t.task_id for t in top if t.task_id}
    ordered = [t for t in buckets["prioridade"] + rest if not blocked(t, open_ids)]
    return sorted(ordered, key=lambda t: t.key not in carry)  # stable: slipped tasks first, the rest keeps its order


def _item(task: BoardTask) -> PlanItem:
    return PlanItem(task.key, task.title, task.needs, PLANNED, task.minutes, f"{task.group}/{task.area}")


def _settle(store: PlanStore, today: date, open_keys: set[str]) -> set[str]:
    """Judge the days that passed since the last time: close their open items (gone from the board = done there,
    still open = postponed), move the capacity, and return the keys that slipped (they come first today)."""
    load = store.load
    slipped: set[str] = set()
    for plan in store.days():
        if load.settled is None or plan.day >= today or plan.day <= load.settled:
            continue  # first run: there is no history worth judging
        for item in plan.items:
            if item.status != PLANNED:
                continue
            if item.task_id in open_keys:
                item.status = POSTPONED
                slipped.add(item.task_id)
            else:
                item.status = DONE  # ticked in the Mind without telling the Jarvis
        counted = plan.counted()
        if counted and load.capacity(plan.day) > 0:
            load.record(plan.day, all(i.status == DONE for i in counted))
    load.settled = today - timedelta(days=1)
    return slipped


def rebalance(store: PlanStore, tasks: list[BoardTask], today: date) -> None:
    """Judge the past, keep today steady and refill today and the next month. An empty board changes nothing
    (it is more likely unreadable than finished)."""
    if not tasks:
        return
    open_keys = {t.key for t in tasks}
    slipped = _settle(store, today, open_keys)
    ordered = _candidates(tasks, today, slipped)
    wanted = {t.key for t in ordered}
    load = store.load

    plan = store.get(today) or DayPlan(today)
    fresh = load.rebalanced != today  # first look at this day: yesterday's forecast for it is not a commitment yet
    kept: list[PlanItem] = []
    for item in plan.items:
        if item.status == PLANNED and fresh:
            continue  # goes back to the pool, so what slipped from yesterday can take its place
        if item.status == PLANNED:
            if item.task_id not in open_keys:
                item.status = DONE  # ticked in the Mind
            elif item.task_id not in wanted:
                continue  # became an idea, blocked, or a sub-item: no longer plannable
        kept.append(item)
    plan.items = kept
    # What the Jarvis already marked done stays out of the pool until the board catches up
    finished = {i.task_id for p in store.days() for i in p.items if i.status == DONE} | {i.task_id for i in plan.items}
    pool = [t for t in ordered if t.key not in finished]

    def fill(day_plan: DayPlan) -> None:
        room = load.capacity(day_plan.day) - len(day_plan.counted())
        areas: dict[str, int] = {}
        for item in day_plan.counted():
            areas[item.area] = areas.get(item.area, 0) + 1
        for task in list(pool):
            if room <= 0:
                break
            area = f"{task.group}/{task.area}"
            if areas.get(area, 0) >= MAX_PER_AREA:
                continue
            day_plan.items.append(_item(task))
            areas[area] = areas.get(area, 0) + 1
            pool.remove(task)
            room -= 1

    fill(plan)
    store.drop_after(today)
    store.put(plan, today)
    for offset in range(1, HORIZON_DAYS):
        later = DayPlan(today + timedelta(days=offset))
        fill(later)
        if later.items:
            store.put(later, today)
    load.rebalanced = today
    store.save(today)


def advance(store: PlanStore, today: date) -> PlanItem | None:
    """Pull the next planned task of a later day into today ("quero adiantar"). Returns it, or None if nothing is ahead."""
    for plan in store.days():
        if plan.day <= today:
            continue
        item = next((i for i in plan.items if i.status == PLANNED), None)
        if item is None:
            continue
        plan.items.remove(item)
        current = store.get(today) or DayPlan(today)
        current.items.append(item)
        store.put(current, today)
        store.put(plan, today)
        return item
    return None


# --- "concluí X": find which task he means -------------------------------------------------------------

_STOP = {"de", "do", "da", "dos", "das", "para", "pra", "com", "que", "uma", "um", "o", "a", "os", "as", "no", "na",
         "em", "ja", "tarefa", "task", "meu", "minha", "isso", "ate"}
_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return [w for w in _WORD.findall(fold(text)) if len(w) >= 3 and w not in _STOP]


def _score(query: list[str], title: list[str]) -> float:
    """Share of the query's words that appear in the title (typos and short forms tolerated)."""
    if not query:
        return 0.0
    hits = 0
    for word in query:
        if any(word == t or (len(word) >= 4 and (t.startswith(word) or word.startswith(t) and len(t) >= 4))
               or difflib.SequenceMatcher(None, word, t).ratio() >= 0.82 for t in title):
            hits += 1
    return hits / len(query)


MATCH_MIN = 0.6


@dataclass(frozen=True)
class Found:
    kind: str                         # "one" | "many" | "none"
    entries: tuple[tuple[str, str], ...] = ()  # (key, title) of the match(es)


def find(query: str, entries: list[tuple[str, str]]) -> Found:
    """Which of `entries` ((key, title) pairs) the words of `query` point to: one, several tied, or none."""
    words = _words(query)
    scored = sorted(((_score(words, _words(title)), key, title) for key, title in entries), reverse=True)
    if not scored or scored[0][0] < MATCH_MIN:
        return Found("none")
    best = [(k, t) for s, k, t in scored if s == scored[0][0]]
    return Found("one", tuple(best)) if len(best) == 1 else Found("many", tuple(best[:4]))


@dataclass(frozen=True)
class Completion:
    kind: str                 # "done" | "again" (already done) | "many" | "none"
    item: PlanItem | None = None
    options: tuple[str, ...] = ()


def complete(store: PlanStore, tasks: list[BoardTask], today: date, query: str) -> Completion:
    """Mark the task he named as done, in today's plan. Looks first at what is planned (any day), then at the board.
    A task planned for another day moves to today: it was done today."""
    planned = [(p.day, i) for p in store.days() for i in p.items if i.status == PLANNED]
    done_today = [i for i in (store.get(today).items if store.get(today) else []) if i.status == DONE]
    found = find(query, [(i.task_id, i.title) for _, i in planned])
    if found.kind == "none":
        again = find(query, [(i.task_id, i.title) for i in done_today])
        if again.kind == "one":
            return Completion("again", next(i for i in done_today if i.task_id == again.entries[0][0]))
        found = find(query, [(t.key, t.title) for t in tasks if t.depth == 0 and not t.idea])
        if found.kind == "one":
            task = next(t for t in tasks if t.key == found.entries[0][0])
            item = _item(task)
            item.status = DONE
            current = store.get(today) or DayPlan(today)
            current.items.append(item)
            store.put(current, today)
            return Completion("done", item)
    if found.kind == "many":
        return Completion("many", options=tuple(title for _, title in found.entries))
    if found.kind == "none":
        return Completion("none")
    key = found.entries[0][0]
    day, item = next((d, i) for d, i in planned if i.task_id == key)
    source = store.get(day)
    if day != today:
        source.items.remove(item)
        store.put(source, today)
        current = store.get(today) or DayPlan(today)
        current.items.append(item)
    else:
        current = source
    item.status = DONE
    store.put(current, today)
    return Completion("done", item)


# --- text ----------------------------------------------------------------------------------------------

_MARK = {PLANNED: "▫️", DONE: "✅", POSTPONED: "⏭️", SKIPPED: "🚫"}
_WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


def _short(title: str, limit: int = 70) -> str:
    return title if len(title) <= limit else title[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-—") + "…"


def _line(item: PlanItem) -> str:
    size = f" (~{item.minutes} min)" if item.minutes else ""
    return f"{_MARK[item.status]} {_short(item.title)}{size}"


def progress(plan: DayPlan | None) -> str:
    counted = plan.counted() if plan else []
    return f"{sum(1 for i in counted if i.status == DONE)} de {len(counted)}"


def _waiting_block(waiting: list[BoardTask]) -> str:
    """The tasks parked with ⏳, so waiting on someone is visible and never mistaken for work left undone."""
    if not waiting:
        return ""
    lines = ["\nAguardando (fora do plano):"]
    lines.extend(f"⏳ {_short(t.title)}" + (f", {t.waiting_for}" if t.waiting_for else "") for t in waiting[:5])
    if len(waiting) > 5:
        lines.append(f"… e mais {len(waiting) - 5}.")
    return "\n".join(lines)


def format_plan(plan: DayPlan | None, store: PlanStore, today: date, waiting: list[BoardTask] | None = None) -> str:
    """Today's plan as a Telegram message, with a one-line look at what comes next and what is parked waiting."""
    load = store.load
    if load.capacity(today) == 0:
        return "Hoje é sábado, senhor: tempo sagrado, nada de tarefa mundana. Descanse."
    if plan is None or not plan.items:
        return "Não achei nada pendente que caiba no seu dia, senhor." + _waiting_block(waiting or [])
    lines = [f"Plano de hoje ({today:%d/%m}), senhor:"]
    lines.extend(_line(i) for i in plan.items)
    lines.append(f"\nFeitas: {progress(plan)}.")
    tomorrow = next((p for p in store.days() if p.day > today and p.items), None)
    if tomorrow:
        lines.append(f"Em seguida ({_WEEKDAYS[tomorrow.day.weekday()]} {tomorrow.day:%d/%m}): {len(tomorrow.items)} tarefa(s).")
    return "\n".join(lines) + _waiting_block(waiting or [])


def format_week(store: PlanStore, today: date, days: int = 7) -> str:
    """The next `days` days, one block each; days with nothing planned are left out."""
    load = store.load
    size = f"{load.fixed} fixas" if load.fixed is not None else f"{load.base}, aprendidas"
    lines = [f"Próximos dias, senhor (capacidade: {size} por dia útil):"]
    for offset in range(days):
        day = today + timedelta(days=offset)
        plan = store.get(day)
        if plan is None or not plan.items:
            continue
        lines.append(f"\n{_WEEKDAYS[day.weekday()]} {day:%d/%m}")
        lines.extend(_line(i) for i in plan.items)
    return "\n".join(lines) if len(lines) > 1 else "Nada planejado para os próximos dias, senhor."
