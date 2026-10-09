"""Understands a closed set of Portuguese time expressions ("amanhã às 9", "sexta 15h",
"daqui a 2 horas", "15/10 14:30"). When it does not understand, or the answer would be a
guess, it returns an Ask with a question instead of inventing a time. Stdlib only."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

WEEKDAYS = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
WEEKDAY_NAMES = (
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo",
)
MONTHS = (
    "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)
NUMBER_WORDS = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
    "oito": 8, "nove": 9, "dez": 10, "quinze": 15, "vinte": 20, "trinta": 30,
}
MAX_AMOUNT = {"minuto": 7 * 24 * 60, "hora": 24 * 31, "dia": 366, "semana": 52}
EXAMPLES = "\"amanhã às 9\", \"sexta às 15h\", \"dia 20 às 10:30\" ou \"daqui a 2 horas\""


@dataclass(frozen=True)
class When:
    dt: datetime
    hour_assumed: bool = False  # True when the hour came from the default, not from the user


@dataclass(frozen=True)
class Ask:
    kind: str  # "entendi" | "hora" | "ampm" | "passou" | "invalido"
    question: str


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def _dont_understand() -> Ask:
    return Ask("entendi", f"Para quando devo marcar, senhor? Entendo coisas como {EXAMPLES}.")


def describe(dt: datetime, now: datetime) -> str:
    """How the date reads back in a confirmation: 'hoje às 15:00', 'amanhã às 09:00', 'sexta-feira, 16/10 às 09:00'."""
    return f"{_day_label(dt, now)} às {dt:%H:%M}"


def _day_label(dt: datetime, now: datetime) -> str:
    delta = (dt.date() - now.date()).days
    if delta in (0, 1):
        return ("hoje", "amanhã")[delta]
    return f"{WEEKDAY_NAMES[dt.weekday()]}, {dt:%d/%m}"


def _relative(text: str, now: datetime) -> When | Ask | None:
    if re.search(r"\b(?:daqui a|daqui|em|dentro de) meia hora\b", text):
        return When((now + timedelta(minutes=30)).replace(second=0, microsecond=0))
    match = re.search(r"\b(?:daqui a|daqui|em|dentro de) (?:(\d+) ?|([a-z]+) )(minutos?|min|horas?|h|dias?|semanas?)\b", text)
    if not match:
        return None
    amount = int(match.group(1)) if match.group(1) else NUMBER_WORDS.get(match.group(2))
    if amount is None:
        return None
    unit = {"min": "minuto", "h": "hora"}.get(match.group(3), match.group(3).rstrip("s"))
    if amount < 1 or amount > MAX_AMOUNT[unit]:
        return Ask("invalido", "Esse prazo me parece fora de proporção, senhor. Pode repetir?")
    delta = {
        "minuto": timedelta(minutes=amount), "hora": timedelta(hours=amount),
        "dia": timedelta(days=amount), "semana": timedelta(weeks=amount),
    }[unit]
    return When((now + delta).replace(second=0, microsecond=0))


def _iso(text: str, now: datetime) -> When | Ask | None:
    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})(?:[ t](\d{1,2}):(\d{2}))?\b", text)
    if not match:
        return None
    year, month, day = (int(match.group(i)) for i in (1, 2, 3))
    try:
        date = datetime(year, month, day, tzinfo=now.tzinfo)
    except ValueError:
        return Ask("invalido", "Essa data não existe, senhor. Pode repetir?")
    if match.group(4) is None:
        return _finish(date, None, now, None)
    return _finish(date, (int(match.group(4)), int(match.group(5))), now, None)


def _strip(text: str, match: re.Match) -> str:
    return text[: match.start()] + " " + text[match.end():]


def _find_date(text: str, now: datetime) -> tuple[datetime | None, str, str | None, Ask | None]:
    """Return (date at 00:00, text without the date words, kind, error).
    kind is 'weekday' for weekday names (they may mean today or next week), else None."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    bad_date = Ask("invalido", "Essa data não existe, senhor. Pode repetir?")

    for word, days in (("depois de amanha", 2), ("amanha", 1), ("hoje", 0)):
        match = re.search(rf"\b{word}\b", text)
        if match:
            return today + timedelta(days=days), _strip(text, match), None, None

    match = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3)) if match.group(3) else None
        if year is not None and year < 100:
            year += 2000
        if not _valid(day, month, year or today.year):
            return None, text, None, bad_date
        return _explicit(day, month, year, today), _strip(text, match), None, None

    month_names = "|".join(MONTHS)
    match = re.search(rf"\bdia (\d{{1,2}})(?: de ({month_names}))?\b", text)
    if match:
        day = int(match.group(1))
        month = MONTHS.index(match.group(2)) + 1 if match.group(2) else None
        found = _day_of_month(day, month, today)
        if found is None:
            return None, text, None, bad_date
        return found, _strip(text, match), None, None

    match = re.search(rf"\b({'|'.join(WEEKDAYS)})(?:-feira)?\b", text)
    if match:
        ahead = (WEEKDAYS.index(match.group(1)) - today.weekday()) % 7
        return today + timedelta(days=ahead), _strip(text, match), "weekday", None
    return None, text, None, None


def _valid(day: int, month: int, year: int) -> bool:
    try:
        datetime(year, month, day)
        return True
    except ValueError:
        return False


def _explicit(day: int, month: int, year: int | None, today: datetime) -> datetime:
    """A date that is known to be valid; without a year, the next time it occurs."""
    if year is None:
        year = today.year
        if _valid(day, month, year) and datetime(year, month, day).date() < today.date():
            year += 1
    return datetime(year, month, day, tzinfo=today.tzinfo)


def _day_of_month(day: int, month: int | None, today: datetime) -> datetime | None:
    if month is not None:
        return _explicit(day, month, None, today) if _valid(day, month, today.year) or _valid(day, month, today.year + 1) else None
    year, mon = today.year, today.month
    for _ in range(13):
        if _valid(day, mon, year) and datetime(year, mon, day).date() >= today.date():
            return datetime(year, mon, day, tzinfo=today.tzinfo)
        mon += 1
        if mon == 13:
            year, mon = year + 1, 1
    return None


def _find_time(text: str) -> tuple[tuple[int, int] | None, bool, Ask | None]:
    """Return ((hour, minute) or None, had_period_word, error). Expects date words already removed."""
    period_match = re.search(r"\b(manha|tarde|noite|madrugada)\b", text)
    period = period_match.group(1) if period_match else None

    if re.search(r"\bmeio[- ]?dia\b", text):
        return (12, 0), True, None
    if re.search(r"\bmeia[- ]?noite\b", text):
        return (0, 0), True, None

    hour = minute = None
    for pattern in (
        r"\b(\d{1,2}):(\d{2})\b",
        r"\b(\d{1,2})\s*(?:h|hr|hrs|horas?)\s*(\d{2})?\b",
        r"\b(\d{1,2}) (?:da|de) (?:manha|tarde|noite|madrugada)\b",
        r"\bas (\d{1,2})\b",
    ):
        match = re.search(pattern, text)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.lastindex and match.lastindex >= 2 and match.group(2) else 0
            break
    if hour is None:
        return None, period is not None, None
    if hour > 23 or minute > 59:
        return None, True, Ask("invalido", "Esse horário não existe, senhor. Pode repetir?")
    if period in ("tarde", "noite") and hour < 12:
        hour += 12
    return (hour, minute), period is not None, None


def _finish(date: datetime, time: tuple[int, int] | None, now: datetime, default_hour: int | None) -> When | Ask:
    if time is None:
        if default_hour is None:
            return Ask("hora", f"Que horas, senhor? Para {_day_label(date, now)}.")
        due = date.replace(hour=default_hour, minute=0)
        assumed = True
    else:
        due = date.replace(hour=time[0], minute=time[1])
        assumed = False
    if due <= now:
        return Ask("passou", "Esse horário já passou, senhor. Para quando devo marcar?")
    return When(due, hour_assumed=assumed)


def parse(text: str, now: datetime, default_hour: int | None = None) -> When | Ask:
    """Turn 'amanhã às 9' into a datetime, or ask. `now` must be timezone-aware.
    `default_hour` fills in the hour when only a day was given; None means ask for it."""
    text = _norm(text)
    if not text:
        return _dont_understand()
    now = now.replace(second=0, microsecond=0)

    for finder in (_relative, _iso):
        found = finder(text, now)
        if found is not None:
            return found

    date, rest, kind, error = _find_date(text, now)
    if error:
        return error
    time, had_period, error = _find_time(rest)
    if error:
        return error

    if date is None:
        if time is None:
            return _dont_understand()
        today = now.replace(hour=0, minute=0)
        today_due = today.replace(hour=time[0], minute=time[1])
        if today_due > now:
            return When(today_due)
        if not had_period and 1 <= time[0] <= 11:
            evening = today.replace(hour=time[0] + 12, minute=time[1])
            if evening > now:
                return Ask("ampm", f"{time[0]}h da manhã de amanhã, ou {time[0] + 12}h de hoje, senhor?")
        return When(today_due + timedelta(days=1))

    if kind == "weekday" and date.date() == now.date():
        time_today_is_ahead = time is not None and date.replace(hour=time[0], minute=time[1]) > now
        if not time_today_is_ahead:
            date += timedelta(days=7)  # "sexta" said on a Friday means next Friday unless the time is still ahead
    return _finish(date, time, now, default_hour)
