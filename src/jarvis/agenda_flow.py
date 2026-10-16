"""Turning "marca reunião com o cliente amanhã às 15" into an event to create, asking for what is missing
(stdlib only). Same rule as the reminders: the code never assumes a day, an hour or an account, it asks.

The model only names WHAT the event is; the day, hour and length come from the owner's own words."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .agenda import Account, account_question, pick_account
from .reminder_request import MANY_TIMES, Planned, PlannedSeries, has_many_times, plan_from_words, split_request, take_duration
from .textutil import fold
from .when import Ask

TTL = timedelta(minutes=10)
DEFAULT_MINUTES = 60
MAX_TITLE_CHARS = 120
CANCELLED = "Tudo bem, senhor, não marquei nada."
_CANCEL = re.compile(r"^(?:nao|n|deixa|esquece|esqueca|cancela|cancelar|nada|melhor nao)\b")
_VERB = re.compile(r"^\W*(?:marc\w*|agend\w*|po[ei]\w*|pon[hd]\w*|coloc\w*|bot[ae]\w*|cri[ae]\w*|adicion\w*)\s+")
_AGENDA_PREFIX = re.compile(r"^\W*(?:(?:na|no|em|a)\s+)?agenda\s+")  # "põe na agenda almoço ..."
_ACCOUNT_WORDS = re.compile(
    r"\b(?:(?:na|no|da|do|de|em|para|pra)\s+)?(?:agenda\s+)?(?:(?:da|do|de)\s+)?"
    r"(?:cafe(?:\s+labs)?|cafelabs|pessoal|profissional|trabalho|empresa)\b")
_LEADING = {"um", "uma", "o", "a", "os", "as", "uns", "umas", "de", "do", "da", "pra", "para", "na", "no", "em", "evento", "compromisso"}
MANY_EVENTS = Ask("varios", "Vejo mais de um horário nessa frase, senhor. Eu marco um evento por vez: pode me pedir o primeiro, e depois o outro?")
RECURRING = Ask("recorrente", "Evento que se repete eu ainda não marco na agenda, senhor. Diga um dia só, ou use um lembrete.")


def title_from_words(said: str) -> str:
    """The event's name out of a whole sentence: "marca amanhã uma reunião com o cliente às 15 na Café" -> "Reunião
    com o cliente". Verb, day, hour, length and the account's name are taken out; what is left is the title."""
    said, _, _ = take_duration(said)
    folded = fold(said)  # same length as `said`, so a span found in one is the same span in the other
    verb = _VERB.match(folded)
    if verb:
        said, folded = said[verb.end():], folded[verb.end():]
    prefix = _AGENDA_PREFIX.match(folded)
    if prefix:
        said, folded = said[prefix.end():], folded[prefix.end():]
    for match in reversed(list(_ACCOUNT_WORDS.finditer(folded))):
        said = said[:match.start()] + " " + said[match.end():]
        folded = folded[:match.start()] + " " + folded[match.end():]
    text, _, _ = split_request(said)
    words = text.split()
    while words and fold(words[0]) in _LEADING:
        words.pop(0)
    title = " ".join(words)
    return title[:1].upper() + title[1:]


@dataclass(frozen=True)
class Plan:
    account: Account
    title: str
    start: datetime
    end: datetime
    assumed_length: bool  # the length was not said: one hour, and the confirmation says so


@dataclass
class _Draft:
    made: datetime
    said: str
    title: str
    when: str
    minutes: int
    hint: str
    account: Account | None
    waiting: str = ""  # what the last question asked for: "hora" | "conta" | "texto"


class AgendaFlow:
    def __init__(self, accounts: tuple[Account, ...], guess_account: bool = False) -> None:
        self._accounts = accounts
        self._guess = guess_account
        self._drafts: dict[int, _Draft] = {}

    def start(self, chat_id: int, said: str, title: str, when: str, minutes: int, hint: str,
              now: datetime) -> Plan | Ask:
        """`said` is what the owner wrote, `title`/`when`/`minutes`/`hint` what the model understood from it."""
        self._drafts.pop(chat_id, None)
        if has_many_times(said):  # two events in one sentence: one would be dropped silently, so say so
            return MANY_EVENTS
        title = " ".join((title or title_from_words(said)).split())[:MAX_TITLE_CHARS]
        return self._plan(chat_id, _Draft(now, said, title, when, minutes, hint, None), now)

    def pending(self, chat_id: int) -> bool:
        return chat_id in self._drafts

    def answer(self, chat_id: int, reply: str, now: datetime) -> Plan | Ask | str | None:
        """The owner's reply to a question of ours. None: nothing was asked. A str: the draft was dropped."""
        draft = self._drafts.get(chat_id)
        if draft is None:
            return None
        if now - draft.made > TTL:
            del self._drafts[chat_id]
            return None
        if _CANCEL.match(fold(reply).strip()):
            del self._drafts[chat_id]
            return CANCELLED
        if draft.waiting == "conta":
            chosen = pick_account(reply, self._accounts)
            if chosen is None:
                return Ask("conta", account_question(self._accounts))
            draft.account = chosen
        elif draft.waiting == "texto":
            draft.title = " ".join(reply.split())[:MAX_TITLE_CHARS]
        else:
            draft.said = f"{draft.said} {reply}"  # "amanhã" ... "às 15"
        return self._plan(chat_id, draft, now)

    def _plan(self, chat_id: int, draft: _Draft, now: datetime) -> Plan | Ask:
        planned = plan_from_words(draft.said, draft.title or "evento", draft.when, 0, now, ask_repeat=False)
        if isinstance(planned, PlannedSeries) or (isinstance(planned, Planned) and planned.repeat):
            self._drafts.pop(chat_id, None)
            return RECURRING
        if isinstance(planned, Ask):
            return self._keep(chat_id, draft, planned, "hora")
        if not draft.title:
            return self._keep(chat_id, draft, Ask("texto", "O que devo marcar, senhor?"), "texto")
        account = draft.account or pick_account(f"{draft.hint} {draft.said} {draft.title}", self._accounts, self._guess)
        if account is None:
            return self._keep(chat_id, draft, Ask("conta", account_question(self._accounts)), "conta")
        minutes = planned.duration or draft.minutes or DEFAULT_MINUTES
        self._drafts.pop(chat_id, None)
        return Plan(account, draft.title, planned.due, planned.due + timedelta(minutes=minutes),
                    assumed_length=not (planned.duration or draft.minutes))

    def _keep(self, chat_id: int, draft: _Draft, ask: Ask, waiting: str) -> Ask:
        draft.waiting = waiting
        self._drafts[chat_id] = draft
        return ask
