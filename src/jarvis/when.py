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
    "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quatorze": 14, "quinze": 15,
    "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19, "vinte": 20, "trinta": 30, "quarenta": 40,
    "cinquenta": 50, "sessenta": 60, "noventa": 90,
}
HOUR_WORDS = {w: n for w, n in NUMBER_WORDS.items() if n <= 12}  # "as nove", "as duas"
PERIOD_NAMES = {"cedo": "cedo", "manha": "da manhã", "tarde": "da tarde", "noite": "da noite", "madrugada": "da madrugada"}
FRACTIONS = {"meia": 30, "quinze": 15, "quarenta e cinco": 45}
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


_TENS = {"vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "noventa": 90}
_UNITS_WORDS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9}


def _compound_numbers(text: str) -> str:
    """"vinte e cinco" -> "25", "quarenta e cinco" -> "45": spoken amounts of minutes and hours."""
    return re.sub(
        rf"\b({'|'.join(_TENS)}) e ({'|'.join(_UNITS_WORDS)})\b",
        lambda m: str(_TENS[m.group(1)] + _UNITS_WORDS[m.group(2)]), text,
    )


def _relative(text: str, now: datetime) -> When | Ask | None:
    text = _compound_numbers(text)
    if re.search(r"\b(?:daqui a|daqui|em|dentro de) meia hora\b", text):
        return When((now + timedelta(minutes=30)).replace(second=0, microsecond=0))
    glued = re.search(r"\b(?:daqui a|daqui|em|dentro de) (\d{1,2})h(\d{2})\b", text)  # "daqui a 1h30"
    if glued and 0 < int(glued.group(1)) * 60 + int(glued.group(2)):
        return When((now + timedelta(hours=int(glued.group(1)), minutes=int(glued.group(2)))).replace(second=0, microsecond=0))
    hm = re.search(r"\b(?:daqui a|daqui|em|dentro de) (\d+) horas? e (\d{1,2}) ?(?:minutos?|min)\b", text)  # "2 horas e 30 minutos"
    if hm and 0 < int(hm.group(2)) < 60 and 0 < int(hm.group(1)) <= 24 * 31:
        return When((now + timedelta(hours=int(hm.group(1)), minutes=int(hm.group(2)))).replace(second=0, microsecond=0))
    half = re.search(
        r"\b(?:daqui a|daqui|em|dentro de) (?:(\d+)|(um|uma|duas|dois|tres|quatro|cinco)) horas? e "
        r"(meia|quinze|quarenta e cinco)\b", text,
    )
    if half:
        hours = int(half.group(1)) if half.group(1) else NUMBER_WORDS[half.group(2)]
        if 1 <= hours <= 24 * 31:
            return When((now + timedelta(hours=hours, minutes=FRACTIONS[half.group(3)])).replace(second=0, microsecond=0))
    match = re.search(r"\b(?:daqui a|daqui|em|dentro de) (?:(\d+) ?|([a-z]+) )(minutos?|min|horas?|h)\b", text)
    if not match:
        return None
    amount = int(match.group(1)) if match.group(1) else NUMBER_WORDS.get(match.group(2))
    if amount is None:
        return None
    unit = {"min": "minuto", "h": "hora"}.get(match.group(3), match.group(3).rstrip("s"))
    if amount < 1 or amount > MAX_AMOUNT[unit]:
        return Ask("invalido", "Esse prazo me parece fora de proporção, senhor. Pode repetir?")
    delta = {"minuto": timedelta(minutes=amount), "hora": timedelta(hours=amount)}[unit]
    return When((now + delta).replace(second=0, microsecond=0))


def _relative_days(text: str, now: datetime) -> tuple[datetime, str] | Ask | None:
    """"daqui a 3 dias", "em 2 semanas": a date, with the hour still to be said ("às 9") or asked. Returns (date, rest)."""
    text = _compound_numbers(text)
    match = re.search(r"\b(?:daqui a|daqui|em|dentro de) (?:(\d+) ?|([a-z]+) )(dias?|semanas?)\b", text)
    if not match:
        return None
    amount = int(match.group(1)) if match.group(1) else NUMBER_WORDS.get(match.group(2))
    if amount is None:
        return None
    unit = match.group(3).rstrip("s")
    if amount < 1 or amount > MAX_AMOUNT[unit]:
        return Ask("invalido", "Esse prazo me parece fora de proporção, senhor. Pode repetir?")
    days = amount * (7 if unit == "semana" else 1)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return today + timedelta(days=days), _strip(text, match)


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
    day_word = r"(\d{1,2}|primeiro)(?:º|o)?"
    match = re.search(rf"\b(?:dia )?{day_word} de ({month_names})(?: de (\d{{4}}))?\b", text)  # "20 de novembro"
    if match:
        day = 1 if match.group(1) == "primeiro" else int(match.group(1))
        month = MONTHS.index(match.group(2)) + 1
        year = int(match.group(3)) if match.group(3) else None
        if not _valid(day, month, year or today.year) and not (year is None and _valid(day, month, today.year + 1)):
            return None, text, None, bad_date
        return _explicit(day, month, year, today), _strip(text, match), None, None

    match = re.search(rf"\b(?:dia )?{day_word} do (\d{{1,2}})\b", text)  # "dia 20 do 11"
    if match:
        day = 1 if match.group(1) == "primeiro" else int(match.group(1))
        month = int(match.group(2))
        if not (1 <= month <= 12) or not (_valid(day, month, today.year) or _valid(day, month, today.year + 1)):
            return None, text, None, bad_date
        return _explicit(day, month, None, today), _strip(text, match), None, None

    match = re.search(rf"\bdia {day_word}\b", text)
    if match:
        day = 1 if match.group(1) == "primeiro" else int(match.group(1))
        found = _day_of_month(day, None, today)
        if found is None:
            return None, text, None, bad_date
        return found, _strip(text, match), None, None

    match = re.search(rf"\b({'|'.join(WEEKDAYS)})(?:[- ]feira)?\b", text)
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
    period_match = re.search(r"\b(cedo|manha|tarde|noite|madrugada)\b", text)
    period = period_match.group(1) if period_match else None

    noon = re.search(r"\bmeio[- ]?dia(?: e (meia|quinze|quarenta e cinco))?\b", text)
    if noon:
        return (12, FRACTIONS.get(noon.group(1) or "", 0)), True, None
    if re.search(r"\bmeia[- ]?noite\b", text):
        return (0, 0), True, None

    hour = minute = None
    words = "|".join(HOUR_WORDS)
    frac = r"(?: e (?P<f>meia|quinze|quarenta e cinco))?"
    for pattern in (
        r"\b(?P<h>\d{1,2}):(?P<m>\d{2})(?:h|hs|hrs)?\b",
        r"\b(?P<h>\d{1,2})\s*(?:h|hr|hrs|horas?)(?: e)?\s*(?P<m>\d{2})?(?: ?min\w*)?\b",
        rf"\b(?P<h>\d{{1,2}}|{words}){frac} (?:da|de) (?:manha|tarde|noite|madrugada)\b",
        rf"\bas (?P<h>\d{{1,2}}|{words}){frac}\b",
    ):
        match = re.search(pattern, text)
        if match:
            raw_hour = match.group("h")
            hour = int(raw_hour) if raw_hour.isdigit() else HOUR_WORDS[raw_hour]
            groups = match.groupdict()
            minute = int(groups["m"]) if groups.get("m") else FRACTIONS.get(groups.get("f") or "", 0)
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
    next_week = bool(re.search(r"\b(?:semana que vem|proxima semana|semana seguinte|outra semana)\b", text))
    text = re.sub(r"\b(?:semana que vem|proxima semana|semana seguinte|outra semana)\b", " ", text)
    proximo = bool(re.search(r"\bproxim[oa] (?:segunda|terca|quarta|quinta|sexta|sabado|domingo)", text))
    text = re.sub(r"\bque vem\b", " ", text)  # "sábado que vem" is the next Saturday, same as "sábado"
    text = re.sub(r"\b(?:proximo|proxima)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return _dont_understand()
    now = now.replace(second=0, microsecond=0)

    for finder in (_relative, _iso):
        found = finder(text, now)
        if found is not None:
            return found

    relative = _relative_days(text, now)
    if isinstance(relative, Ask):
        return relative
    if relative is not None:
        date, rest = relative
        kind, error = None, None
    else:
        date, rest, kind, error = _find_date(text, now)
    if error:
        return error
    today = now.replace(hour=0, minute=0)
    if next_week:  # "sexta da semana que vem": that Friday of next week, not this week's
        if kind != "weekday":
            return _dont_understand()
        date, kind = today + timedelta(days=7 - today.weekday() + date.weekday()), None
    elif proximo and kind == "weekday" and date.date() == now.date():
        date += timedelta(days=7)  # "próxima segunda" said on a Monday is next week's
    if date is None and re.search(r"\b(?:janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|"
                                  r"dezembro|semana|semanas|mes|meses|ano|anos|ontem|anteontem|natal|fds|fim|carnaval|pascoa|reveillon)\b", rest):
        return _dont_understand()  # a date was said but not understood: never fall back to "the next time it is that hour"
    time, had_period, error = _find_time(rest)
    if error:
        return error
    if re.search(r"\bmeia[- ]?noite\b", rest) and (date is None or date.date() == now.date()):
        date, kind, time = today + timedelta(days=1), None, (0, 0)  # "hoje à meia noite": the coming midnight, 00:00 tomorrow
    if time is None:
        period = re.search(r"\b(cedo|manha|tarde|noite|madrugada)\b", rest)
        if period:  # "amanhã de manhã": which hour of the morning? never guessed
            where = f" Para {_day_label(date, now)}." if date is not None else ""
            what = "Que horas, senhor?" if period.group(1) == "cedo" else f"Que horas {PERIOD_NAMES[period.group(1)]}, senhor?"
            return Ask("hora", what + where)

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
    if time is not None and not had_period and 1 <= time[0] <= 6:  # "amanhã às 3": morning or afternoon?
        if date.date() == now.date() and date.replace(hour=time[0], minute=time[1]) <= now:
            time = (time[0] + 12, time[1])  # today's morning is over: it can only mean the afternoon
            return _finish(date, time, now, default_hour)
        return Ask("ampm", f"Às {time[0]}h da manhã ou da tarde, senhor? Para {_day_label(date, now)}.")
    return _finish(date, time, now, default_hour)
