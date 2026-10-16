"""The calendar side of the assistant, without any network: which of the owner's accounts a thing belongs to,
which days a question covers, what one merged agenda looks like (stdlib only).

The owner keeps three Google accounts and sees them as a single calendar on the phone, so the agenda is read
from all of them at once and the same event living in two accounts is shown once."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .gcal import Event
from .textutil import fold
from .when import WEEKDAY_NAMES, Ask, When, parse

DEFAULT_LABELS = {"trabalho": "profissional", "pessoal": "pessoal", "cafe": "Café Labs"}
# Words that name an account outright, and words that only suggest one. "reunião pessoal" is personal: the
# explicit word beats the guess.
_EXPLICIT = {
    "cafe": {"cafe", "cafelabs", "cafe labs", "empresa"},
    "pessoal": {"pessoal", "particular"},
    "trabalho": {"trabalho", "profissional"},
}
_SUGGESTS = {
    "cafe": {"reuniao", "reunioes", "cliente", "call", "daily", "sprint", "proposta"},
    "pessoal": {"viagem", "viajar", "lazer", "familia", "aniversario", "passeio", "ferias", "medico", "dentista",
                "consulta", "igreja", "cinema", "namorada", "amigos"},
}
MAX_DAYS = 31


@dataclass(frozen=True)
class Account:
    key: str       # "trabalho" | "pessoal" | "cafe" (or any name the owner chose)
    label: str     # how it reads in a reply
    calendar: str  # the Google calendar id (the account's e-mail)


def parse_accounts(value: str | None) -> tuple[Account, ...]:
    """'trabalho=a@x.com,pessoal=b@y.com,cafe=c@z.com' -> accounts, in the order written. Bad pieces are skipped."""
    accounts: list[Account] = []
    for piece in (value or "").split(","):
        key, _, calendar = piece.partition("=")
        key, calendar = fold(key).replace(" ", ""), calendar.strip()
        if key and "@" in calendar and all(a.key != key for a in accounts):
            accounts.append(Account(key, DEFAULT_LABELS.get(key, key), calendar))
    return tuple(accounts)


def _words(text: str) -> set[str]:
    folded = fold(text)
    return set(re.findall(r"[a-z0-9]+", folded)) | {folded}


def _hits(text: str, table: dict[str, set[str]], accounts: tuple[Account, ...]) -> list[Account]:
    folded = fold(text)
    words = _words(text)
    found = []
    for account in accounts:
        names = table.get(account.key, set()) | {account.key}
        if any((n in words) or (" " in n and n in folded) for n in names):
            found.append(account)
    return found


def pick_account(text: str, accounts: tuple[Account, ...], guess: bool = False) -> Account | None:
    """The account the owner NAMED ("na pessoal", "da Café"), or None when none or two are named (then the caller
    asks). With `guess`, the subject also counts ("reunião com o cliente" points to Café); off by default, because
    the owner prefers to be asked every time."""
    for table in (_EXPLICIT, _SUGGESTS) if guess else (_EXPLICIT,):
        found = _hits(text, table, accounts)
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            return None
    return None


def account_question(accounts: tuple[Account, ...]) -> str:
    names = ", ".join(a.label for a in accounts[:-1]) + (" ou " if len(accounts) > 1 else "") + accounts[-1].label
    return f"Em qual agenda, senhor: {names}?"


def by_calendar(accounts: tuple[Account, ...], calendar: str) -> Account | None:
    return next((a for a in accounts if a.calendar == calendar), None)


# --- which days a question covers --------------------------------------------------------------------------------

_WHICH_DAY = "Qual dia, senhor? Entendo “hoje”, “amanhã”, “sexta”, “dia 20” ou “essa semana”."
_DAY_WORD = re.compile(r"\b(?:hoje|amanha|segunda|terca|quarta|quinta|sexta|sabado|domingo|dia \d|\d{1,2}/\d{1,2}|\d{1,2} de [a-z]+)")
_WEEK = re.compile(r"\b(?:semana|proximos dias|proximos \d+ dias|essa semana|esta semana)\b")


def window(text: str, now: datetime) -> tuple[datetime, datetime, str] | Ask:
    """(start, end, label) for 'hoje', 'amanhã', 'sexta', 'dia 20', 'essa semana'. Empty means today."""
    folded = fold(text)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if not folded.strip() or re.fullmatch(r"\W*(?:hoje|agora)\W*", folded):
        return today, today + timedelta(days=1), "hoje"
    if _WEEK.search(folded):
        return today, today + timedelta(days=7), "nos próximos 7 dias"
    if not _DAY_WORD.search(folded):  # without this, any gibberish would parse as "today at that hour"
        return Ask("entendi", _WHICH_DAY)
    # reuse the date vocabulary of the reminders; the hour is only there so the date parser is satisfied
    parsed = parse(f"{folded} as 23:59", now)
    if isinstance(parsed, Ask):
        return Ask("entendi", _WHICH_DAY)
    day = parsed.dt.replace(hour=0, minute=0)
    return day, day + timedelta(days=1), _day_name(day, now)


def _day_name(day: datetime, now: datetime) -> str:
    delta = (day.date() - now.date()).days
    if delta in (0, 1):
        return ("hoje", "amanhã")[delta]
    return f"{WEEKDAY_NAMES[day.weekday()]}, {day:%d/%m}"


# --- the merged agenda -------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Shown:
    copies: tuple[tuple[Account, Event], ...]  # every account that has it (the same meeting is often in two)

    @property
    def event(self) -> Event:
        return self.copies[0][1]

    @property
    def accounts(self) -> tuple[Account, ...]:
        return tuple(account for account, _ in self.copies)

    @property
    def ref(self) -> str:
        """Where to find every copy again, to move or delete it: 'trabalho:id1;cafe:id2'."""
        return ";".join(f"{account.key}:{event.id}" for account, event in self.copies)


def parse_ref(ref: str, accounts: tuple[Account, ...]) -> list[tuple[Account, str]]:
    """The inverse of Shown.ref; pieces for unknown accounts are dropped."""
    found = []
    for piece in ref.split(";"):
        key, _, event_id = piece.partition(":")
        account = next((a for a in accounts if a.key == key), None)
        if account and event_id:
            found.append((account, event_id))
    return found


def merge(per_account: list[tuple[Account, list[Event]]]) -> list[Shown]:
    """One entry per real event, in time order. Same title at the same time in two accounts is one event."""
    merged: dict[tuple, list] = {}
    for account, events in per_account:
        for event in events:
            merged.setdefault((fold(event.title), event.start, event.end), []).append((account, event))
    shown = [Shown(tuple(copies)) for copies in merged.values()]
    return sorted(shown, key=lambda s: (s.event.start, s.event.end, s.event.title))


def _span(event: Event) -> str:
    return "dia todo" if event.all_day else f"{event.start:%H:%M}–{event.end:%H:%M}"


def line(item: Shown) -> str:
    where = f" — {item.event.location}" if item.event.location else ""
    return f"{_span(item.event)}  {item.event.title}{where} ({' e '.join(a.label for a in item.accounts)})"


def listing(items: list[Shown], label: str, now: datetime, failed: list[Account] | None = None) -> str:
    """The agenda as chat text. A single day is a flat list; several days are grouped under the day.
    `failed` are accounts that could not be read: said, never hidden."""
    several = label.startswith("nos")
    if not items:
        text = f"Não há nada marcado {label}, senhor."
    else:
        lines = [f"Agenda {label}, senhor:" if several else f"Agenda de {label}, senhor:"]
        day = None
        for item in items:
            if several and item.event.start.date() != day:
                day = item.event.start.date()
                name = _day_name(item.event.start.replace(hour=0, minute=0), now)
                lines += ["", name[0].upper() + name[1:] + ":"]
            lines.append("• " + line(item))
        text = "\n".join(lines)
    if failed:
        text += f"\n\nNão consegui ler: {', '.join(a.label for a in failed)}."
    return text


def overlapping(items: list[Shown], start: datetime, end: datetime) -> list[Shown]:
    """Events that overlap [start, end). All-day events do not block a time slot."""
    return [i for i in items if not i.event.all_day and i.event.start < end and i.event.end > start]


def search(items: list[Shown], words: str) -> list[Shown]:
    """Events whose title has every word the owner used (accent and case ignored)."""
    wanted = [w for w in re.findall(r"[a-z0-9]+", fold(words)) if len(w) > 2]
    if not wanted:
        return []
    return [i for i in items if all(w in fold(i.event.title) for w in wanted)]


def describe(event: Event, now: datetime) -> str:
    """'amanhã 15:00–16:00', for the confirmation questions."""
    return f"{_day_name(event.start.replace(hour=0, minute=0), now)} {_span(event)}"
