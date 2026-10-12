"""Splits a free sentence like "ligar pro João amanhã às 9, 10 min antes" into WHAT to remember,
WHEN it happens and how much ADVANCE warning, without calling a model. The "when" part is then
interpreted by `when.parse`; this module only finds which words belong to it. Stdlib only."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

from .when import HOUR_WORDS, MONTHS, NUMBER_WORDS, WEEKDAYS, Ask, parse
from .reminder_text import human_minutes
from .repeat import align_first, extract

MAX_LEAD_MINUTES = 24 * 60

_WEEKDAY = re.compile(rf"^({'|'.join(WEEKDAYS)})(-feira)?$")
_TIME = re.compile(r"^\d{1,2}(?:h|hs|hr|hrs)\d{0,2}$|^\d{1,2}:\d{2}$")
_DATE = re.compile(r"^\d{1,2}/\d{1,2}(?:/\d{2,4})?$|^\d{4}-\d{2}-\d{2}(?:t\d{1,2}:\d{2})?$")
_NUMBER = re.compile(r"^\d{1,4}$")
_DAY_WORDS = {"hoje", "amanha", "meio-dia", "meia-noite"}
_PERIODS = {"cedo", "manha", "tarde", "noite", "madrugada"}
_UNITS = {"min", "minuto", "minutos", "hora", "horas", "h", "dia", "dias", "semana", "semanas"}
_CONNECTORS = {"de", "da", "do", "a", "ao", "as", "em", "daqui", "dentro", "dia", "depois", "meia", "meio", "que", "vem", "e"}
_VOCAB = (_DAY_WORDS | _PERIODS | _UNITS | _CONNECTORS | set(NUMBER_WORDS) | set(MONTHS))
_LEAD_FILLER = {"uns", "umas"}
_BEFORE_DAY = {"na", "no", "nesta", "neste", "nessa", "nesse"}  # "na sexta", "no dia 15": part of the when
_TEXT_LEAD = {"de", "da", "do", "das", "dos", "que", "para", "pra", "a", "o", "e"}
_TEXT_TAIL = {"em", "de", "para", "pra", "a", "as", "e", "do", "da"}


@dataclass(frozen=True)
class Planned:
    text: str
    due: datetime
    event: datetime | None  # set when `due` is an advance warning
    lead_minutes: int
    hour_assumed: bool
    repeat: str | None = None  # "daily" | "weekdays" | "weekly"


def _norm(token: str) -> str:
    token = unicodedata.normalize("NFKD", token.lower())
    token = "".join(c for c in token if not unicodedata.combining(c))
    return token.strip(",.;:!?()\"'“”")


def _is_vocab(token: str) -> bool:
    return bool(
        token in _VOCAB or _WEEKDAY.match(token) or _TIME.match(token) or _DATE.match(token) or _NUMBER.match(token)
    )


def _is_content(token: str) -> bool:
    """A "when" phrase can end here (connectors like 'de' or 'às' can not end a phrase)."""
    return bool(
        token in _DAY_WORDS or token in _PERIODS or token in _UNITS - {"dia"} or token in set(MONTHS)
        or _WEEKDAY.match(token) or _TIME.match(token) or _DATE.match(token) or _NUMBER.match(token)
    )


def _can_end(norm: list[str], k: int) -> bool:
    """Whether a "when" phrase may end at norm[k]: also on "e meia", "que vem" and "meio dia"."""
    token, before = norm[k], norm[k - 1] if k > 0 else ""
    return (_is_content(token) or (token == "meia" and before == "e") or (token == "vem" and before == "que")
            or (token == "dia" and before == "meio"))


def _is_strong(tokens: list[str]) -> bool:
    """Enough evidence that this run of words is really a time, not just words like 'de tarde'."""
    for i, token in enumerate(tokens):
        if token in _DAY_WORDS or token in {"daqui", "dentro"} or _WEEKDAY.match(token) or _TIME.match(token) \
                or _DATE.match(token) or token in set(MONTHS):
            return True
        following = tokens[i + 1] if i + 1 < len(tokens) else ""
        if token == "as" and (_NUMBER.match(following) or following in HOUR_WORDS):
            return True
        if (token == "meio" and following == "dia") or (token == "meia" and following == "noite") or token == "cedo":
            return True
        if token in {"de", "a"} and following in {"manha", "tarde", "noite"}:  # "de manhã", "à noite"
            return True
        if token == "em" and (_NUMBER.match(following) or following in NUMBER_WORDS or following == "meia"):
            return True
        if token == "dia" and _NUMBER.match(following):
            return True
    return False


def _take_lead(norm: list[str]) -> tuple[int, set[int]]:
    """Find '<n> min|hora(s) antes' (also 'meia hora antes', '10min antes'). Returns (minutes, token indexes)."""
    for i, token in enumerate(norm):
        if token != "antes" or i < 2:
            continue
        unit, amount = norm[i - 1], norm[i - 2]
        used = {i, i - 1, i - 2}
        glued = re.match(r"^(\d+)(min|m|h)$", norm[i - 1])
        if glued:  # "10min antes", "1h antes"
            minutes = int(glued.group(1)) * (60 if glued.group(2) == "h" else 1)
            used = {i, i - 1}
        elif unit in {"min", "minuto", "minutos", "hora", "horas", "h"}:
            if amount == "meia" and unit.startswith("hora"):
                minutes = 30
            else:
                value = int(amount) if amount.isdigit() else NUMBER_WORDS.get(amount)
                if value is None:
                    continue
                minutes = value * (60 if unit.startswith("h") else 1)
        else:
            continue
        first = min(used)
        if first > 0 and norm[first - 1] in _LEAD_FILLER:  # "uns 10 min antes"
            used.add(first - 1)
        return minutes, used
    return 0, set()


def _strong_runs(norm: list[str], skip: set[int]) -> list[tuple[int, int]]:
    """(start, end_exclusive) of every strong, trimmed run of "when" words, skipping removed tokens."""
    runs, i = [], 0
    while i < len(norm):
        if i in skip or not _is_vocab(norm[i]):
            i += 1
            continue
        j = i
        while j < len(norm) and j not in skip and _is_vocab(norm[j]):
            j += 1
        start, end = i, j
        while end > start and not _can_end(norm, end - 1):
            end -= 1  # a phrase can not end on 'de', 'às'...
        first = start  # strength is judged with the leading "de"/"a" still there ("de manhã", "à noite")
        while start < end:
            token = norm[start]
            following = norm[start + 1] if start + 1 < end else ""
            keep_em = token == "em" and (_NUMBER.match(following) or following in NUMBER_WORDS or following == "meia")
            if token in {"de", "da", "do", "que", "e", "vem"} or (token == "a") or (token == "em" and not keep_em):
                start += 1
            else:
                break
        if start < end and _is_strong(norm[first:end]):
            if start > 0 and start - 1 not in skip and norm[start - 1] in _BEFORE_DAY \
                    and (_WEEKDAY.match(norm[start]) or norm[start] == "dia"):
                start -= 1  # "na sexta que vou ao médico": the "na" belongs to the day, not to the text
            runs.append((start, end))
        i = j
    return runs


def _clean_text(tokens: list[str]) -> str:
    while tokens and _norm(tokens[0]) in _TEXT_LEAD:
        tokens = tokens[1:]
    while tokens and _norm(tokens[-1]) in _TEXT_TAIL:
        tokens = tokens[:-1]
    return " ".join(tokens).strip(" ,;:-?!.")  # a transcribed question mark is not part of the text


def split_request(raw: str) -> tuple[str, str, int]:
    """Return (text to remember, when phrase, lead minutes). The phrase is empty if no time was found."""
    if "|" in raw:  # explicit "quando | o quê" (either order) beats any guessing
        left, _, right = raw.partition("|")
        for when_side, text_side in ((left, right), (right, left)):
            if _only_when(when_side):
                _, phrase, lead = split_request(when_side)
                if phrase:
                    return _clean_text(text_side.split()), phrase, lead
    tokens = raw.split()
    norm = [_norm(t) for t in tokens]
    lead, lead_idx = _take_lead(norm)
    runs = _strong_runs(norm, lead_idx)
    in_run = {k for start, end in runs for k in range(start, end)}
    phrase = " ".join(norm[k] for start, end in runs for k in range(start, end))
    rest = [t for k, t in enumerate(tokens) if k not in in_run and k not in lead_idx]
    return _clean_text(rest), phrase, lead


def _only_when(side: str) -> bool:
    """True when the whole side is made of "when" words (so it can be the left of 'quando | texto')."""
    norm = [_norm(t) for t in side.split()]
    return bool(norm) and all(_is_vocab(t) or t in {"antes", "uns", "umas"} for t in norm)


def plan_parts(text: str, phrase: str, lead: int, now: datetime, default_hour: int | None = None,
               repeat: str | None = None) -> Planned | Ask:
    """Plan a reminder whose pieces are already separated (what, when in words, minutes of advance).
    A repeat can come in `repeat` or inside `phrase` ("todo dia às 9")."""
    if repeat is None:
        found = extract(phrase)
        if found.ask:
            return found.ask
        phrase, repeat = found.rest, found.repeat
    if not text.strip():
        return Ask("texto", "O que devo lembrar, senhor?")
    if lead > MAX_LEAD_MINUTES:
        return Ask("invalido", "Essa antecedência é grande demais, senhor. Pode repetir?")
    when = parse(phrase, now, default_hour)
    if isinstance(when, Ask):
        return when
    anchor = align_first(when.dt, repeat)
    due = anchor - timedelta(minutes=lead)
    if due <= now:
        return Ask(
            "passou",
            f"Com {human_minutes(lead)} de antecedência o aviso já teria passado, senhor. Para quando devo marcar?",
        )
    return Planned(text.strip(), due, anchor if lead else None, lead, when.hour_assumed, repeat)


def plan_reminder(raw: str, now: datetime, default_hour: int | None = None) -> Planned | Ask:
    """Plan a reminder from one free sentence (the /lembra command and "me lembra ...")."""
    found = extract(raw)
    if found.ask:
        return found.ask
    text, phrase, lead = split_request(found.rest)
    if not phrase:
        return parse("", now)  # the standard "para quando devo marcar?" question
    return plan_parts(text, phrase, lead, now, default_hour, found.repeat)
