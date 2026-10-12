"""What a reminder sounds like when it is delivered: Jarvis's tone, written by the code, not the
model (free, instant, works when the model is down). Forms rotate and never repeat the last one.
No jokes: reminders are about deadlines and money."""
from __future__ import annotations

import random
from datetime import datetime

from .repeat import label
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
ON_TIME_BEFORE = (
    "Senhor, faltam {falta} para {texto} (às {hora}).",
    "Perdoe a interrupção, senhor. Faltam {falta}: {texto}, às {hora}.",
    "Aviso prévio, senhor: {texto} é às {hora}, daqui a {falta}.",
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


def human_minutes(total: int) -> str:
    """90 -> '1 hora e 30 minutos', 10 -> '10 minutos', 120 -> '2 horas'."""
    hours, minutes = divmod(total, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hora" + ("s" if hours > 1 else ""))
    if minutes:
        parts.append(f"{minutes} minuto" + ("s" if minutes > 1 else ""))
    return " e ".join(parts) or "0 minutos"


def _when(due: datetime, now: datetime) -> str:
    days = (now.date() - due.date()).days
    if days == 0:
        return f"{due:%H:%M}"
    if days == 1:
        return f"ontem às {due:%H:%M}"
    return f"{due:%d/%m} às {due:%H:%M}"


def _lines(items: list[Reminder], now: datetime) -> str:
    return "\n".join(f"{i}. {_when(r.event or r.due, now)} — {_body(r.text)}" for i, r in enumerate(items, 1))


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
        if len(items) == 1 and items[0].event:
            r = items[0]
            falta = human_minutes(round((r.event - r.due).total_seconds() / 60))
            return self._pick(ON_TIME_BEFORE).format(falta=falta, hora=f"{r.event:%H:%M}", texto=_body(r.text))
        if len(items) == 1:
            r = items[0]
            return self._pick(ON_TIME).format(hora=f"{r.due:%H:%M}", texto=_body(r.text))
        return self._pick(ON_TIME_MANY).format(n=len(items)) + "\n" + _lines(items, now)

    def late(self, late: list[Reminder], lost: list[Reminder], now: datetime) -> str:
        parts = []
        if len(late) == 1:
            r = late[0]
            parts.append(self._pick(LATE_ONE).format(quando=_when(r.event or r.due, now), texto=_body(r.text)))
        elif late:
            parts.append(self._pick(LATE_MANY) + "\n" + _lines(late, now))
        if lost:
            parts.append(LOST_HEADER + "\n" + _lines(lost, now))
        return "\n\n".join(parts)


def confirmation(reminder: Reminder, now: datetime, hour_assumed: bool = False) -> str:
    """What the code says right after a reminder is stored. The model never writes this."""
    from .when import describe

    if reminder.event:
        falta = human_minutes(round((reminder.event - reminder.due).total_seconds() / 60))
        text = (f"Marcado, senhor (lembrete {reminder.id}). Aviso {describe(reminder.due, now)}, "
                f"{falta} antes de {_body(reminder.text)} (às {reminder.event:%H:%M}).")
    else:
        text = f"Marcado, senhor (lembrete {reminder.id}): {describe(reminder.due, now)}, {_body(reminder.text)}."
    if reminder.repeat:
        text += f" Repito {label(reminder.repeat, reminder.event or reminder.due)}."
    if reminder.duration:
        text += f" Dura {human_minutes(reminder.duration)}."
    if hour_assumed:
        text += (f" Não disse a hora, então assumi {reminder.due:%H:%M}; se preferir outra, "
                 f"cancele com /cancela {reminder.id} e marque de novo.")
    return text


def series_confirmation(reminders: list[Reminder], now: datetime, hour_assumed: bool = False) -> str:
    """One message for "toda segunda e quarta às 7": every reminder created, with its own number."""
    numbers = ", ".join(str(r.id) for r in reminders[:-1]) + f" e {reminders[-1].id}"
    if any(r.event for r in reminders):  # with advance warning each day reads differently: list them one by one
        return "\n".join(confirmation(r, now, False) for r in reminders) + (
            f"\nNão disse a hora, então assumi {reminders[0].due:%H:%M}." if hour_assumed else ""
        )
    days = " e ".join(label(r.repeat, r.due) for r in reminders)
    text = f"Marcado, senhor (lembretes {numbers}): {days} às {reminders[0].due:%H:%M}, {_body(reminders[0].text)}."
    if reminders[0].duration:
        text += f" Dura {human_minutes(reminders[0].duration)}."
    if hour_assumed:
        text += (f" Não disse a hora, então assumi {reminders[0].due:%H:%M}; se preferir outra, "
                 f"cancele com /cancela {reminders[0].id} e /cancela {reminders[-1].id} e marque de novo.")
    return text


def listing(items: list[Reminder], now: datetime) -> str:
    from .when import describe

    if not items:
        return "Não há lembretes pendentes, senhor."
    lines = [f"Lembretes pendentes, senhor ({len(items)}):"]
    for r in items:
        extra = f" (aviso; evento às {r.event:%H:%M})" if r.event else ""
        again = f" (repete {label(r.repeat, r.event or r.due)})" if r.repeat else ""
        lasts = f" (dura {human_minutes(r.duration)})" if r.duration else ""
        lines.append(f"{r.id}. {describe(r.due, now)}{extra}{again}{lasts} — {_body(r.text)}")
    lines.append("")
    lines.append("Para cancelar: /cancela <número>.")
    return "\n".join(lines)
