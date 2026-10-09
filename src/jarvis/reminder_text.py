"""What a reminder sounds like when it is delivered: Jarvis's tone, written by the code, not the
model (free, instant, works when the model is down). Forms rotate and never repeat the last one.
No jokes: reminders are about deadlines and money."""
from __future__ import annotations

import random
from datetime import datetime

from .reminders import Reminder

ON_TIME = (
    "Senhor, lembrete das {hora}: {texto}.",
    "Perdoe a interrupção, senhor. Lembrete: {texto}.",
    "Às {hora}, senhor, como o senhor pediu: {texto}.",
    "Conforme solicitado, senhor: {texto}. São {hora}.",
    "Com licença, senhor. Está na hora: {texto}.",
)
ON_TIME_MANY = (
    "Senhor, {n} lembretes neste momento:",
    "Perdoe a interrupção, senhor. Há {n} lembretes agora:",
    "Conforme solicitado, senhor, {n} lembretes:",
)
LATE_ONE = (
    "Perdoe o atraso, senhor. Isto era para {quando}: {texto}.",
    "Com atraso, senhor. Estava marcado para {quando}: {texto}.",
)
LATE_MANY = (
    "Perdoe o atraso, senhor. Estes lembretes ficaram para trás enquanto estive fora:",
    "Senhor, estes lembretes venceram enquanto eu estava fora do ar:",
)
LOST_HEADER = "Estes venceram há mais de 24 horas e não cheguei a entregar:"


def _body(text: str) -> str:
    return text.rstrip(" .!?;:,")


def _when(due: datetime, now: datetime) -> str:
    days = (now.date() - due.date()).days
    if days == 0:
        return f"{due:%H:%M}"
    if days == 1:
        return f"ontem às {due:%H:%M}"
    return f"{due:%d/%m} às {due:%H:%M}"


def _lines(items: list[Reminder], now: datetime) -> str:
    return "\n".join(f"{i}. {_when(r.due, now)} — {_body(r.text)}" for i, r in enumerate(items, 1))


class ReminderVoice:
    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self._last: dict[int, int] = {}  # per form list, the last index used

    def _pick(self, forms: tuple[str, ...]) -> str:
        key = id(forms)
        choices = [i for i in range(len(forms)) if i != self._last.get(key)]
        index = self._rng.choice(choices)
        self._last[key] = index
        return forms[index]

    def on_time(self, items: list[Reminder], now: datetime) -> str:
        if len(items) == 1:
            r = items[0]
            return self._pick(ON_TIME).format(hora=f"{r.due:%H:%M}", texto=_body(r.text))
        return self._pick(ON_TIME_MANY).format(n=len(items)) + "\n" + _lines(items, now)

    def late(self, late: list[Reminder], lost: list[Reminder], now: datetime) -> str:
        parts = []
        if len(late) == 1:
            r = late[0]
            parts.append(self._pick(LATE_ONE).format(quando=_when(r.due, now), texto=_body(r.text)))
        elif late:
            parts.append(self._pick(LATE_MANY) + "\n" + _lines(late, now))
        if lost:
            parts.append(LOST_HEADER + "\n" + _lines(lost, now))
        return "\n\n".join(parts)
