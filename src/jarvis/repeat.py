"""Repeating reminders: finds "todo dia", "toda segunda", "dias úteis" in a request and works out the
next occurrence. A closed set (daily, weekdays, weekly); anything else (monthly...) gets a question
instead of a guess. Stdlib only."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

from .when import WEEKDAY_NAMES, WEEKDAYS, Ask

DAILY, WEEKDAYS_ONLY, WEEKLY = "daily", "weekdays", "weekly"
KINDS = (DAILY, WEEKDAYS_ONLY, WEEKLY)
_PERIODS = {"manha", "tarde", "noite", "madrugada"}
_UNSUPPORTED = Ask(
    "repeticao",
    "Por enquanto repito por dia, em dias úteis ou num dia da semana, senhor (ex.: \"todo dia às 8\", \"toda segunda às 9\"). "
    "Por mês ainda não. Como prefere?",
)
_NEEDS_WEEKDAY = Ask("repeticao", "Em que dia da semana, senhor? Por exemplo: \"toda segunda às 9\".")
_WEEKDAY_WORD = re.compile(rf"^({'|'.join(WEEKDAYS)})s?(?:-feiras?)?$")
_ALL = {"todo", "toda", "todos", "todas"}


@dataclass(frozen=True)
class Extraction:
    rest: str                 # the request without the repeat words (a weekday name stays, it is the first date)
    repeat: str | None
    ask: Ask | None = None


def _n(token: str) -> str:
    token = unicodedata.normalize("NFKD", token.lower())
    token = "".join(c for c in token if not unicodedata.combining(c))
    return token.strip(",.;!?()\"'“”")


def _weekday(word: str) -> str | None:
    match = _WEEKDAY_WORD.match(word)
    return match.group(1) if match else None


def extract(raw: str) -> Extraction:
    """Take the repeat words out of a free sentence. Returns the rest, the kind (or None) or a question."""
    tokens = raw.split()
    n = [_n(t) for t in tokens]
    repeat: str | None = None
    weekly_any = False
    i = 0
    out: list[str] = []
    while i < len(tokens):
        word, nxt, third, fourth = (n[i + k] if i + k < len(n) else "" for k in range(4))
        if word in _ALL and nxt in {"os", "as", "a"} and third in {"dias", "dia"} and repeat is None:
            repeat, i = (WEEKDAYS_ONLY, i + 4) if fourth in {"util", "uteis"} else (DAILY, i + 3)
            continue
        if word in {"todo", "todos"} and nxt == "dia" and repeat is None:
            if third in {"util", "uteis"}:
                repeat, i = WEEKDAYS_ONLY, i + 3
            elif third.isdigit() or third in {"primeiro", "ultimo"}:
                return Extraction(raw, None, _UNSUPPORTED)  # "todo dia 20" is monthly
            else:
                repeat, i = DAILY, i + 2
            continue
        if word in {"nos", "em"} and nxt == "dias" and third in {"uteis", "util"} and repeat is None:
            repeat, i = WEEKDAYS_ONLY, i + 3
            continue
        if word == "dias" and nxt in {"uteis", "util"} and repeat is None:
            repeat, i = WEEKDAYS_ONLY, i + 2
            continue
        if word == "de" and nxt == "segunda" and third == "a" and fourth in {"sexta", "sexta-feira"} and repeat is None:
            repeat, i = WEEKDAYS_ONLY, i + 4
            continue
        if word == "diariamente" and repeat is None:
            repeat, i = DAILY, i + 1
            continue
        if word in {"mensalmente", "anualmente", "quinzenalmente"} or (word in _ALL and nxt in {"mes", "meses", "ano", "anos"}):
            return Extraction(raw, None, _UNSUPPORTED)
        if word == "semanalmente" and repeat is None:
            repeat, weekly_any, i = WEEKLY, True, i + 1
            continue
        if word in _ALL and repeat is None:
            skip = 1 + (nxt in {"os", "as"})
            following = n[i + skip] if i + skip < len(n) else ""
            if _weekday(following):  # "toda segunda", "todas as sextas", "todo sábado"
                repeat = WEEKLY
                out.append(_weekday(following))
                i += skip + 1
                continue
            if following in _PERIODS:  # "toda noite às 9": every day, the period word stays to place the hour
                repeat = DAILY
                out.append(tokens[i + skip])
                i += skip + 1
                continue
            if following in {"semana", "semanas"}:
                repeat, weekly_any = WEEKLY, True
                i += skip + 1
                continue
        out.append(tokens[i])
        i += 1
    if repeat is None:
        return Extraction(raw, None)
    if weekly_any:
        names = [_weekday(_n(t)) for t in out]
        if not any(names):
            return Extraction(raw, None, _NEEDS_WEEKDAY)
        out = _drop_prepositions_before_weekday(out)
    return Extraction(" ".join(out), repeat)


def _drop_prepositions_before_weekday(tokens: list[str]) -> list[str]:
    kept = []
    for k, token in enumerate(tokens):
        after = _n(tokens[k + 1]) if k + 1 < len(tokens) else ""
        if _n(token) in {"na", "no", "nas", "nos", "em"} and _weekday(after):
            continue
        kept.append(token)
    return kept


def align_first(anchor: datetime, repeat: str | None) -> datetime:
    """The first occurrence of a weekdays-only reminder never lands on a weekend."""
    if repeat == WEEKDAYS_ONLY:
        while anchor.weekday() >= 5:
            anchor += timedelta(days=1)
    return anchor


def next_occurrence(anchor: datetime, repeat: str, now: datetime, lead: timedelta = timedelta(0)) -> datetime:
    """The first occurrence after `anchor` whose warning time (`occurrence - lead`) is still ahead of `now`."""
    step = timedelta(days=7 if repeat == WEEKLY else 1)
    candidate = anchor
    while True:
        candidate += step
        if repeat == WEEKDAYS_ONLY and candidate.weekday() >= 5:
            continue
        if candidate - lead > now:
            return candidate


def label(repeat: str, anchor: datetime) -> str:
    if repeat == DAILY:
        return "todos os dias"
    if repeat == WEEKDAYS_ONLY:
        return "nos dias úteis"
    name = WEEKDAY_NAMES[anchor.weekday()]
    return ("todo " if anchor.weekday() >= 5 else "toda ") + name
