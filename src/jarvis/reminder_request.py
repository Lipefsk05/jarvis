"""Splits a free sentence like "ligar pro João amanhã às 9, 10 min antes" into WHAT to remember,
WHEN it happens and how much ADVANCE warning, without calling a model. The "when" part is then
interpreted by `when.parse`; this module only finds which words belong to it. Stdlib only."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .when import HOUR_WORDS, MONTHS, NUMBER_WORDS, WEEKDAYS, Ask, _find_time, parse
from .reminder_text import human_minutes
from .repeat import DAILY, WEEKDAYS_ONLY, WEEKLY, align_first, extract, label
from .textutil import fold

MAX_LEAD_MINUTES = 24 * 60

_WEEKDAY = re.compile(rf"^({'|'.join(WEEKDAYS)})(-feira)?$")
_ORDINAL = re.compile(r"^\d{1,2}[ºo]$")
_TIME = re.compile(r"^\d{1,2}(?:h|hs|hr|hrs)\d{0,2}$|^\d{1,2}:\d{2}(?:h|hs|hrs)?$")
_DATE = re.compile(r"^\d{1,2}/\d{1,2}(?:/\d{2,4})?$|^\d{4}-\d{2}-\d{2}(?:t\d{1,2}:\d{2})?$")
_NUMBER = re.compile(r"^\d{1,6}$")
_DAY_WORDS = {"hoje", "amanha", "meio-dia", "meia-noite"}
_PERIODS = {"cedo", "manha", "tarde", "noite", "madrugada"}
_UNITS = {"min", "minuto", "minutos", "hora", "horas", "h", "dia", "dias", "semana", "semanas"}
_CONNECTORS = {"de", "da", "do", "a", "ao", "as", "das", "mes", "meses", "ano", "anos", "natal", "ontem", "anteontem", "fds", "fim", "carnaval", "pascoa", "reveillon", "proximo", "proxima", "seguinte", "feira", "mais", "primeiro", "em", "daqui", "dentro", "dia", "depois", "meia", "meio", "que", "vem", "e"}
_VOCAB = (_DAY_WORDS | _PERIODS | _UNITS | _CONNECTORS | set(NUMBER_WORDS) | set(MONTHS))
_LEAD_FILLER = {"uns", "umas"}
_BEFORE_DAY = {"na", "no", "nesta", "neste", "nessa", "nesse"}  # "na sexta", "no dia 15": part of the when
_TEXT_LEAD = {"de", "da", "do", "das", "dos", "que", "para", "pra", "a", "o", "e", "ai", "entao"}
_TEXT_TAIL = {"em", "de", "para", "pra", "a", "as", "e", "do", "da"}


@dataclass(frozen=True)
class Planned:
    text: str
    due: datetime
    event: datetime | None  # set when `due` is an advance warning
    lead_minutes: int
    hour_assumed: bool
    repeat: str | None = None  # "daily" | "weekdays" | "weekly"


# Things people usually do again and again: a one-off reminder about them is probably meant to repeat.
_ROUTINE = re.compile(
    r"\b(?:remedio\w*|medicament\w*|vitamin\w*|comprimid\w*|agua|hidrat\w*|academia|trein\w*|malhar|musculacao|"
    r"corrida|correr|caminhad\w*|caminhar|alongar\w*|estudar|estudo|ingles|aula|curso|oracao|orar|rezar|terco|medit\w*|"
    r"escovar|acordar|dormir|standup|daily|diari\w*|rotina|yoga|pilates|natacao|fisioterapia|terapia|psicolog\w*)\b"
)
_NOT_ROUTINE = re.compile(r"\b(?:pag\w+|boleto|fatura|conta|mensalidade|aluguel)\b")  # bills are monthly, which can not repeat yet
_ONCE = re.compile(r"\b(?:so (?:hoje|amanha|essa vez|esta vez|dessa vez|desta vez)|uma vez|uma unica vez|apenas hoje|nao repete|sem repetir)\b")
REPEAT_QUESTION = Ask(
    "repetir",
    "Isso parece algo de rotina, senhor. Quer que eu repita? Diga \"todo dia\", \"dias úteis\", \"toda segunda e quarta\"..., "
    "ou \"só desta vez\".",
)


def _repeat_question(text: str, said: str) -> Ask | None:
    """Ask whether a one-off reminder should repeat when it reads like a routine (and the user did not say once)."""
    folded, spoken = fold(text), fold(said)
    if _ROUTINE.search(folded) and not _NOT_ROUTINE.search(folded) and not _ONCE.search(spoken):
        return REPEAT_QUESTION
    return None


@dataclass(frozen=True)
class PlannedSeries:
    """"Toda segunda e quarta às 7": one weekly reminder per day, stored together and confirmed in one message."""
    items: tuple[Planned, ...]


def _norm(token: str) -> str:
    token = unicodedata.normalize("NFKD", token.lower())
    token = "".join(c for c in token if not unicodedata.combining(c))
    return token.strip(",.;:!?()\"'“”")


def _is_vocab(token: str) -> bool:
    return bool(
        token in _VOCAB or _ORDINAL.match(token) or _WEEKDAY.match(token) or _TIME.match(token) or _DATE.match(token) or _NUMBER.match(token)
    )


def _is_content(token: str) -> bool:
    """A "when" phrase can end here (connectors like 'de' or 'às' can not end a phrase)."""
    return bool(
        token in _DAY_WORDS or token in _PERIODS or token in _UNITS - {"dia"} or token in set(MONTHS) or _ORDINAL.match(token)
        or _WEEKDAY.match(token) or _TIME.match(token) or _DATE.match(token) or _NUMBER.match(token)
    )


def _can_end(norm: list[str], k: int) -> bool:
    """Whether a "when" phrase may end at norm[k]: also on "às nove", "e meia", "e quinze", "que vem", "meio dia"."""
    token, before = norm[k], norm[k - 1] if k > 0 else ""
    return (_is_content(token) or (token == "meia" and before == "e") or (token == "vem" and before == "que")
            or (token == "dia" and before == "meio") or (token in HOUR_WORDS and before == "as")
            or (token in NUMBER_WORDS and before == "e") or (token == "cinco" and before == "quarenta")
            or (token == "feira" and bool(_WEEKDAY.match(before))) or (token == "primeiro" and before == "dia"))


def _is_strong(tokens: list[str]) -> bool:
    """Enough evidence that this run of words is really a time, not just words like 'de tarde'."""
    for i, token in enumerate(tokens):
        if token in _DAY_WORDS or token in {"daqui", "dentro"} or _WEEKDAY.match(token) or _TIME.match(token) \
                or _DATE.match(token) or token in set(MONTHS):
            return True
        following = tokens[i + 1] if i + 1 < len(tokens) else ""
        if token in {"as", "das"} and (_NUMBER.match(following) or following in HOUR_WORDS):
            return True
        if (token == "meio" and following == "dia") or (token == "meia" and following == "noite") or token == "cedo":
            return True
        if token in {"de", "a", "mais"} and following in {"manha", "tarde", "noite"}:  # "de manhã", "à noite", "mais tarde"
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
        elif unit in {"min", "minuto", "minutos", "hora", "horas", "h", "dia", "dias", "semana", "semanas"}:
            if amount == "meia" and unit.startswith("hora"):
                minutes = 30
            else:
                value = int(amount) if amount.isdigit() else NUMBER_WORDS.get(amount)
                if value is None:
                    continue
                minutes = value * {"m": 1, "h": 60, "d": 1440, "s": 10080}[unit[0]]
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
            if token in {"de", "da", "do", "que", "e", "vem", "mais", "proximo", "proxima"} or (token == "a") or (token == "em" and not keep_em):
                start += 1
            elif _NUMBER.match(token) and (following in _DAY_WORDS or _WEEKDAY.match(following) or following in {"as", "dia", "daqui", "em", "depois"}):
                start += 1  # "ligar pro 190 amanhã": the 190 belongs to the text
            else:
                break
        if start < end and _is_strong(norm[first:end]):
            if _WEEKDAY.match(norm[start]) or norm[start] in {"dia", "proximo", "proxima"}:
                while start > 0 and start - 1 not in skip and norm[start - 1] in _BEFORE_DAY | {"proximo", "proxima"}:
                    start -= 1  # "na sexta que vou...", "no próximo domingo": "na", "no", "próximo" belong to the day
            runs.append((start, end))
        i = j
    return runs


_PERIOD_WORDS = _PERIODS | {"de", "da", "a", "mais"}


def _has_exact_time(tokens: list[str]) -> bool:
    return any(_TIME.match(t) or (t in {"as", "das"} and k + 1 < len(tokens) and (_NUMBER.match(tokens[k + 1]) or tokens[k + 1] in HOUR_WORDS))
               or (t == "meio" and k + 1 < len(tokens) and tokens[k + 1] == "dia") for k, t in enumerate(tokens))


def _time_count(tokens: list[str]) -> int:
    """How many exact hours the tokens name ("às 9 e às 15" -> 2)."""
    return sum(1 for k, t in enumerate(tokens)
               if _TIME.match(t) or (t in {"as", "das"} and k + 1 < len(tokens) and (_NUMBER.match(tokens[k + 1]) or tokens[k + 1] in HOUR_WORDS)))


def has_many_times(raw: str) -> bool:
    """True when the sentence names more than one hour ("amanhã às 9 e às 15", "às 9 ou 10"): one reminder can not
    have two, and picking the first one silently would mark the wrong thing."""
    norm = [_norm(t) for t in raw.split()]
    _, lead_idx = _take_lead(norm)
    runs = _strong_runs(norm, lead_idx)
    spoken = [norm[k] for start, end in runs for k in range(start, end)]
    if _time_count(spoken) >= 2:
        return True
    return any(end < len(norm) - 1 and norm[end] == "ou" and (_NUMBER.match(norm[end + 1]) or _TIME.match(norm[end + 1])
                                                                or norm[end + 1] in HOUR_WORDS) for _, end in runs)


MANY_TIMES = Ask("varios", "Vejo mais de um horário nessa frase, senhor. Pode pedir um lembrete de cada vez?")


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
    if len(runs) > 1 and any(_has_exact_time(norm[a:b]) for a, b in runs):  # "reunião de tarde ... amanhã às 15": the first
        runs = [(a, b) for a, b in runs if _has_exact_time(norm[a:b]) or not all(t in _PERIOD_WORDS for t in norm[a:b])]  # is text
    in_run = {k for start, end in runs for k in range(start, end)}
    phrase = " ".join(norm[k] for start, end in runs for k in range(start, end))
    rest = [t for k, t in enumerate(tokens) if k not in in_run and k not in lead_idx]
    return _clean_text(rest), phrase, lead


def _only_when(side: str) -> bool:
    """True when the whole side is made of "when" words (so it can be the left of 'quando | texto')."""
    norm = [_norm(t) for t in side.split()]
    return bool(norm) and all(_is_vocab(t) or t in {"antes", "uns", "umas"} for t in norm)


def plan_parts(text: str, phrase: str, lead: int, now: datetime, default_hour: int | None = None,
               repeat: str | None = None, ask_repeat: bool = True) -> Planned | PlannedSeries | Ask:
    """Plan a reminder whose pieces are already separated (what, when in words, minutes of advance).
    A repeat can come in `repeat` or inside `phrase` ("todo dia às 9")."""
    if repeat is None:
        found = extract(phrase)
        if found.ask:
            return found.ask
        if found.days:
            return _per_day(found.days, lambda day: (text, f"{day} {found.rest}", lead), now, default_hour)
        phrase, repeat = found.rest, found.repeat
    if not text.strip():
        return Ask("texto", "O que devo lembrar, senhor?")
    if lead > MAX_LEAD_MINUTES:
        return Ask("invalido", "Essa antecedência é grande demais, senhor. Pode repetir?")
    when = parse(phrase, now, default_hour)
    if isinstance(when, Ask):
        return _no_time(repeat, now) if when.kind == "entendi" and repeat in (DAILY, WEEKDAYS_ONLY) else when
    anchor = align_first(when.dt, repeat)
    due = anchor - timedelta(minutes=lead)
    if due <= now:
        return Ask(
            "passou",
            f"Com {human_minutes(lead)} de antecedência o aviso já teria passado, senhor. Para quando devo marcar?",
        )
    planned = Planned(text.strip(), due, anchor if lead else None, lead, when.hour_assumed, repeat)
    if ask_repeat and repeat is None:
        return _repeat_question(planned.text, phrase) or planned
    return planned


def _no_time(repeat: str | None, now: datetime) -> Ask:
    """Nothing about the time was said. A daily or weekday repeat only lacks the hour, so that is what is asked."""
    if repeat in (DAILY, WEEKDAYS_ONLY):
        return Ask("hora", f"Que horas, senhor? Para repetir {label(repeat, now)}.")
    return parse("", now)  # the standard "para quando devo marcar?" question


def _per_day(days: tuple[str, ...], pieces, now: datetime, default_hour: int | None) -> PlannedSeries | Ask:
    """One weekly reminder per weekday. `pieces(day)` gives (text, when phrase, lead minutes) for that day."""
    items = []
    for day in days:
        text, phrase, lead = pieces(day)
        if not phrase:
            return _no_time(WEEKLY, now)
        planned = plan_parts(text, phrase, lead, now, default_hour, WEEKLY)
        if isinstance(planned, Ask):
            return planned
        items.append(planned)
    return PlannedSeries(tuple(items))


def plan_reminder(raw: str, now: datetime, default_hour: int | None = None,
                  ask_repeat: bool = True) -> Planned | PlannedSeries | Ask:
    """Plan a reminder from one free sentence (the /lembra command and "me lembra ...")."""
    found = extract(raw)
    if found.ask:
        return found.ask
    if found.days:
        return _per_day(found.days, lambda day: split_request(f"{day} {found.rest}"), now, default_hour)
    if has_many_times(found.rest):
        return MANY_TIMES
    text, phrase, lead = split_request(found.rest)
    if not phrase:
        return _no_time(found.repeat, now)
    planned = plan_parts(text, phrase, lead, now, default_hour, found.repeat, ask_repeat=False)
    if ask_repeat and isinstance(planned, Planned) and planned.repeat is None:
        return _repeat_question(planned.text, raw) or planned
    return planned


def plan_from_words(user_text: str, model_text: str, model_when: str, lead: int, now: datetime,
                    default_hour: int | None = None, ask_repeat: bool = True) -> Planned | PlannedSeries | Ask:
    """A reminder the model chose to create. The model names WHAT to remember; WHEN is read from the user's
    own words when they hold a time, because the model drops details ("terças e quintas" -> "terça", "duas da
    tarde" -> nothing). Only when the user's words hold no time does the model's `quando` count."""
    planned = plan_reminder(user_text, now, default_hour, ask_repeat=False)
    if isinstance(planned, Ask):
        if planned.kind in {"entendi", "texto"}:  # no time found in what the user wrote
            return plan_parts(model_text, model_when, lead, now, default_hour, ask_repeat=ask_repeat)
        return planned  # a time was there but needs a question (hour, morning or evening, repeat)
    if isinstance(planned, PlannedSeries):
        return PlannedSeries(tuple(replace(item, text=model_text) for item in planned.items))
    planned = replace(planned, text=model_text)
    if ask_repeat and planned.repeat is None:
        return _repeat_question(model_text, user_text) or planned
    return planned


def is_schedule(text: str) -> bool:
    """A sentence that is a repeating schedule with a clock time ("toda terça e sexta academia às 15"). It carries
    no "me lembra", but a repeat plus an exact hour is almost always a request for a reminder, so the code makes it."""
    found = extract(text)
    if found.ask or found.repeat is None:
        return False
    _, phrase, _ = split_request(found.rest)
    time, _, error = _find_time(phrase) if phrase else (None, False, None)
    return time is not None and error is None
