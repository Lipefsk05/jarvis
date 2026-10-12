"""Position marks the Felipe reports in plain words ("cheguei no trampo", "saí agora", "desci em casa"):
which anchor of the day it is, when it happened, and the reply the code sends back. Pure functions; the
bot stores the result in the PlanStore."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .plan import Habits, resolve_anchors
from .textutil import fold

MARK_ANCHOR = {
    "saida_casa": "leave_home", "chegada_trabalho": "arrive_work",
    "saida_trabalho": "leave_work", "chegada_casa": "arrive_home",
}
AMBIGUOUS = ("chegada", "saida")  # "cheguei" / "saí" with no place
MARKS = tuple(MARK_ANCHOR) + AMBIGUOUS
MAX_FUTURE = timedelta(minutes=5)  # a time slightly ahead of the clock is tolerated (clock drift, "9:40" said at 9:38)

_NOW = re.compile(r"^(?:agora|agorinha|ja|agr|neste momento|)$")
_AGO = re.compile(r"\b(?:ha|faz|fazem)\s+(\d{1,3})\s*(?:min|minutos?|h|horas?)\b")
_CLOCK = re.compile(r"\b(?:as\s+)?(\d{1,2})\s*(?:[:h]\s*(\d{2})?)(?!\d)|\bas\s+(\d{1,2})\b")


@dataclass(frozen=True)
class MarkAsk:
    question: str


def parse_moment(text: str, now: datetime) -> datetime | MarkAsk:
    """When the mark happened, today: "" or "agora" = now; "9:40", "às 9", "9h15"; "há 10 minutos".
    A time that is still hours ahead is refused (nothing here is planned in the future)."""
    folded = " ".join(fold(text).split())
    if _NOW.match(folded):
        return now
    ago = _AGO.search(folded)
    if ago:
        amount = int(ago.group(1))
        unit = timedelta(hours=amount) if re.search(r"(?:h|horas?)\b", folded[ago.start(1):]) else timedelta(minutes=amount)
        return now - unit
    clock = _CLOCK.search(folded)
    if clock:
        hour = int(clock.group(1) or clock.group(3))
        minute = int(clock.group(2) or 0)
        if hour > 23 or minute > 59:
            return MarkAsk("Que horas foi isso, senhor?")
        moment = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if moment > now + MAX_FUTURE:
            return MarkAsk(f"{hour:02d}:{minute:02d} ainda não chegou, senhor. Que horas foi?")
        return moment
    return MarkAsk("Que horas foi isso, senhor? Diga por exemplo \"agora\", \"às 9:40\" ou \"há 10 minutos\".")


def resolve_ambiguous(mark: str, told: dict[str, datetime], now: datetime) -> str | MarkAsk:
    """"Cheguei" / "saí" with no place: decide from what was already told today, else ask."""
    if mark == "chegada":
        if not told and now.hour < 13:
            return "arrive_work"
        if "leave_work" in told and "arrive_home" not in told:
            return "arrive_home"
        if "leave_home" in told and "arrive_work" not in told:
            return "arrive_work"
        return MarkAsk("Chegou onde, senhor, no trabalho ou em casa?")
    if "arrive_work" in told and "leave_work" not in told:
        return "leave_work"
    if not told and now.hour < 11:
        return "leave_home"
    return MarkAsk("Saiu de onde, senhor, de casa ou do trabalho?")


_WORK_WORDS = re.compile(r"\b(?:trabalh\w*|trampo|servico|empresa|estagio)\b")
_HOME_WORDS = re.compile(r"\bcasa\b")


def answer_place(ambiguous: str, text: str) -> str | None:
    """The concrete mark when `text` is a short answer to "no trabalho ou em casa?" ("em casa", "no trampo"),
    else None. Several words or both places mean it is not a plain answer."""
    folded = fold(text)
    if len(folded.split()) > 6:
        return None
    work, home = bool(_WORK_WORDS.search(folded)), bool(_HOME_WORDS.search(folded))
    if work == home:
        return None
    suffix = "trabalho" if work else "casa"
    return f"{ambiguous}_{suffix}"


FOLLOWUP = {"arrive_home": "leave_work", "leave_work": "arrive_work"}  # the step before, worth asking about if skipped
MISSED = {"leave_work": "a saída do trabalho", "arrive_work": "a chegada ao trabalho"}
MAX_ANSWER_WORDS = 5


def missing_step(anchor: str, told: dict[str, datetime]) -> str | None:
    """The earlier anchor the Felipe skipped (he said he is home but never said he left work), else None.
    Only the step right before is asked about, so one message never turns into a quiz."""
    step = FOLLOWUP.get(anchor)
    return step if step and step not in told else None


def ask_missing(step: str) -> str:
    return f"Não me avisou {MISSED[step]}; a que horas foi, senhor?"


def answer_time(text: str, now: datetime) -> datetime | None:
    """The time when `text` is a short answer to "a que horas foi?" ("15:40", "às 3 e meia" is not understood
    and falls through to normal chat); None for anything else, so a real new message is never swallowed."""
    if len(text.split()) > MAX_ANSWER_WORDS:
        return None
    moment = parse_moment(text, now)
    return None if isinstance(moment, MarkAsk) else moment


LABEL = {
    "leave_home": "saiu de casa", "arrive_work": "chegou ao trabalho",
    "leave_work": "saiu do trabalho", "arrive_home": "chegou em casa",
}


def confirmation(anchor: str, moment: datetime, told: dict[str, datetime], habits: Habits, tz) -> str:
    """The reply after recording a mark, with what it changes in the day."""
    moments, _ = resolve_anchors(moment.date(), told, habits, tz)
    head = f"Anotado, senhor: {LABEL[anchor]} às {moment:%H:%M}."
    if anchor == "leave_home":
        return f"{head} Chegada ao trabalho por volta das {moments['arrive_work']:%H:%M}."
    if anchor == "arrive_work":
        return f"{head} Pelo expediente de {habits.work_minutes // 60} h, a saída fica por volta das {moments['leave_work']:%H:%M}."
    if anchor == "leave_work":
        return f"{head} Em casa por volta das {moments['arrive_home']:%H:%M}; no ônibus dá pra adiantar o que for de celular."
    return f"{head} A noite está livre a partir daí."

