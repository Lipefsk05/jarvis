"""The conversation around one reminder request: the question the code asked and the answer that completes it.

A request that is missing something ("amanhã de manhã" has no hour, "tomar remédio" may be a routine) is never
guessed: the code asks, remembers the half-made request for a few minutes and merges the next message into it.
The model is not involved in the questions or the answers, so the behaviour is the same whichever model created
the reminder (a stronger model only has to name the text better). Stdlib only."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .commands import is_yes, parse_reminder_request
from .reminder_request import (
    REPEAT_QUESTION, Planned, PlannedSeries, is_only_when, is_schedule, plan_from_words, plan_reminder, split_request,
)
from .repeat import WEEKLY, extract
from .textutil import fold
from .when import HOUR_WORDS, Ask

TTL = timedelta(minutes=10)
# Questions whose answer completes the request. Others ("this date does not exist", "too far") are plain replies.
DRAFT_KINDS = {"entendi", "texto", "hora", "ampm", "passou", "repetir", "frequencia", "dia_semana"}
FREQUENCY_QUESTION = Ask(
    "frequencia",
    "Com que frequência, senhor? Todo dia, nos dias úteis, ou numa semana (diga os dias, ex.: \"toda segunda e quarta\").",
)
CANCELLED = "Tudo bem, senhor, não marquei nada."

_CANCEL = re.compile(r"^(?:nao|n|deixa|esquece|esqueca|cancela|cancelar|nada|nenhum|melhor nao)\b")
_ONCE = re.compile(r"^(?:nao|n|so|apenas|somente|uma vez|sem repetir)\b")
_FILLER = {"sim", "quero", "pode", "ser", "isso", "claro", "favor", "pfv", "aham", "uhum", "bora", "manda", "entao",
           "faz", "faca", "coloca", "coloque", "poe", "marca", "marque", "seria", "bom", "ok", "beleza", "blz", "e"}
_DAY_WORDS = re.compile(r"\b(?:depois de amanh[ãa]|amanh[ãa]|hoje)\b", re.IGNORECASE)
_BARE_HOUR = re.compile(
    rf"^(?:(?:as|a|pode ser|umas?|por volta das?) )?(?P<h>\d{{1,2}}|{'|'.join(HOUR_WORDS)})"
    r"(?:(?::| ?h) ?(?P<m>\d{2})?|(?: e (?P<f>meia|quinze|quarenta e cinco)))?"
    r"(?: horas?)?(?P<rest>(?: (?:da|de|na|no) \w+)?)$"
)


@dataclass(frozen=True)
class Dropped:
    """The user gave up ("deixa pra lá"): nothing was stored."""
    message: str


@dataclass(frozen=True)
class _Draft:
    raw: str              # everything the user said about this reminder so far
    text: str | None      # the model's wording of WHAT, when the model created it (else read from `raw`)
    when: str             # the model's `quando`: used only when the user's own words hold no time
    lead: int             # the model's advance warning in minutes
    kind: str             # the kind of question waiting for an answer
    repeat_asked: bool    # the "do you want it repeated?" question was already asked (or answered "once")
    at: datetime


def strip_filler(reply: str) -> str:
    """"sim, pode ser às 8" -> "às 8": courtesy words in front of an answer carry no information."""
    reply = re.sub(r"^(?:por favor,? )", "", reply.strip(), flags=re.IGNORECASE)
    reply = re.sub(r"\b(?:por volta d[aeo]s?)\b", "às", reply, flags=re.IGNORECASE)
    words = reply.split()
    while words and fold(words[0]).strip(" ,.!?") in _FILLER:
        words.pop(0)
    return " ".join(words) if words else reply


def hour_answer(reply: str) -> str:
    """"8" -> "as 8", "oito e meia" -> "as oito e meia", "3 da tarde" stays: an answer to "que horas?" is a bare hour."""
    folded = fold(reply).strip(" .!?,")
    match = _BARE_HOUR.match(folded)
    if not match:
        return reply
    hour = match.group("h")
    if match.group("m"):
        clock = f"{hour}:{match.group('m')}"
    elif match.group("f"):
        clock = f"{hour} e {match.group('f')}"
    else:
        clock = hour
    return f"as {clock}{match.group('rest') or ''}"


class ReminderFlow:
    """Per-chat half-made reminder requests. `start` plans one; `answer` feeds the next message to it."""

    def __init__(self, ttl: timedelta = TTL) -> None:
        self._ttl = ttl
        self._drafts: dict[int, _Draft] = {}

    def pending(self, chat_id: int) -> bool:
        return chat_id in self._drafts

    def clear(self, chat_id: int) -> None:
        self._drafts.pop(chat_id, None)

    def start(self, chat_id: int, raw: str, now: datetime, *, text: str | None = None, when: str = "",
              lead: int = 0) -> Planned | PlannedSeries | Ask:
        """Plan a reminder from the user's words. `text`/`when`/`lead` are what the model understood, if it created it."""
        return self._run(chat_id, _Draft(raw, text, when, lead, "", False, now), now)

    def answer(self, chat_id: int, message: str, now: datetime) -> Planned | PlannedSeries | Ask | Dropped | None:
        """Use `message` as the answer to the pending question. None when there is nothing pending or the message is
        not an answer to it (the caller then treats it as a normal message)."""
        draft = self._drafts.pop(chat_id, None)
        if draft is None or now - draft.at > self._ttl:
            return None
        if parse_reminder_request(message) is not None or is_schedule(message):  # a new request, not an answer
            return None
        folded = fold(message).strip(" .!?,")
        if draft.kind in {"repetir", "frequencia"}:
            return self._answer_repeat(chat_id, draft, message, folded, now)
        if _CANCEL.match(folded):
            return Dropped(CANCELLED)
        message = strip_filler(message)
        if draft.kind in {"hora", "ampm", "passou", "entendi"} and not is_only_when(message):
            return None  # a time was asked: anything with other words in it is a new message, not the answer
        if draft.kind == "passou":  # the new time replaces the one that already went by; keep only what to remember
            base = "" if draft.text is not None else split_request(extract(draft.raw).rest)[0]
            merged = replace(draft, raw=f"{base} {message}".strip())
        else:
            reply = hour_answer(message) if draft.kind in {"hora", "ampm"} else message
            raw = _DAY_WORDS.sub(" ", draft.raw) if draft.kind == "dia_semana" else draft.raw  # the weekday decides the day
            merged = replace(draft, raw=f"{raw} {reply}")
        result = self._plan(merged, now)
        if isinstance(result, Ask) and result.kind == draft.kind:  # the same question again: it did not answer it
            return None
        if isinstance(result, Ask) and result.kind in {"entendi", "texto"}:
            return None
        return self._remember(chat_id, merged, result, now)

    # -- internals

    def _answer_repeat(self, chat_id: int, draft: _Draft, message: str, folded: str, now: datetime):
        asked = replace(draft, repeat_asked=True)
        if draft.kind == "repetir" and (_ONCE.match(folded) or _CANCEL.match(folded)):
            return self._run(chat_id, asked, now)  # one time only
        if is_yes(message):  # "sim": how often?
            self._drafts[chat_id] = replace(asked, kind="frequencia", at=now)
            return FREQUENCY_QUESTION
        message = strip_filler(message)
        raw = draft.raw
        found = extract(message)
        if found.days or (found.repeat == WEEKLY):  # "toda terça": the weekday decides the first day, not an earlier "amanhã"
            raw = _DAY_WORDS.sub(" ", raw)
        merged = replace(asked, raw=f"{raw} {message}")
        result = self._plan(merged, now)
        repeats = isinstance(result, PlannedSeries) or (isinstance(result, Planned) and result.repeat)
        if isinstance(result, Ask) and result.kind in DRAFT_KINDS - {"repetir", "frequencia", "entendi", "texto"}:
            return self._remember(chat_id, replace(merged, kind=result.kind), result, now)  # e.g. "toda semana": which day?
        if not repeats:  # the answer said nothing about repeating: it was something else
            return None
        return self._remember(chat_id, merged, result, now)

    def _plan(self, draft: _Draft, now: datetime) -> Planned | PlannedSeries | Ask:
        ask = not draft.repeat_asked
        if draft.text is None:
            return plan_reminder(draft.raw, now, None, ask_repeat=ask)
        return plan_from_words(draft.raw, draft.text, draft.when, draft.lead, now, None, ask_repeat=ask)

    def _run(self, chat_id: int, draft: _Draft, now: datetime):
        return self._remember(chat_id, draft, self._plan(draft, now), now)

    def _remember(self, chat_id: int, draft: _Draft, result, now: datetime):
        if isinstance(result, Ask) and result.kind in DRAFT_KINDS:
            self._drafts[chat_id] = replace(
                draft, kind=result.kind, at=now, repeat_asked=draft.repeat_asked or result is REPEAT_QUESTION,
            )
        else:
            self._drafts.pop(chat_id, None)
        return result
