"""What the Telegram bot does with the agenda tools. The model only names the action; the day, the hour, the
account and the confirmations are decided here, and the text sent back is written here, never by the model."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from .actions import Action
from .agenda import Shown, account_question, describe, line, listing, window
from .agenda_flow import AgendaFlow, Plan
from .agenda_service import Agenda
from .assistant import Assistant
from .gcal import CalendarError, new_event_id
from .reminder_request import Planned, plan_from_words
from .when import Ask, describe as day_time

log = logging.getLogger("jarvis")

UNDO_PREFIX = "agund"  # callback data: agund:<account key>:<event id>
FORCED = "forcado"  # Action.ref of a create the owner already approved despite a clash
NOT_FOUND = "Não achei esse compromisso nos próximos 60 dias, senhor."
MAX_LIST = 6


def _numbered(items: list[Shown]) -> str:
    return "\n".join(f"{n}. {line(item)}" for n, item in enumerate(items, 1))


def _failure(exc: CalendarError) -> str:
    if exc.status in (403, 404):
        return ("O Google não deixou, senhor: essa agenda não está compartilhada com a conta de serviço do Jarvis "
                "com permissão de alterar eventos.")
    return f"Não consegui falar com o Google Calendar agora, senhor ({exc})."


class AgendaHandlers:
    def __init__(self, agenda: Agenda, flow: AgendaFlow, assistant: Assistant, clock: Callable[[], datetime]) -> None:
        self._agenda, self._flow, self._assistant, self._clock = agenda, flow, assistant, clock

    async def _say(self, message, chat_id: int, text: str, remember: str | None = None, markup=None) -> None:
        await message.reply_text(text, reply_markup=markup)
        self._assistant.remember(chat_id, text if remember is None else remember)

    # --- entry points ---------------------------------------------------------------------------------------

    async def run(self, message, chat_id: int, action: Action, user_text: str = "") -> None:
        if action.name == "consultar_agenda":
            await self._read(message, chat_id, action.quando or user_text)
        elif action.name == "criar_evento":
            await self._create(message, chat_id, action, user_text)
        elif action.name == "mover_evento":
            await (self._do_move if action.ref else self._propose_move)(message, chat_id, action, user_text)
        elif action.name == "cancelar_evento":
            await (self._do_cancel if action.ref else self._propose_cancel)(message, chat_id, action)

    async def answer(self, message, chat_id: int, text: str) -> bool:
        """The reply to a question about an event being created. False when none was waiting."""
        result = self._flow.answer(chat_id, text, self._clock())
        if result is None:
            return False
        if isinstance(result, str):
            await message.reply_text(result)
        else:
            await self._after_plan(message, chat_id, result)
        return True

    # --- reading --------------------------------------------------------------------------------------------

    async def _read(self, message, chat_id: int, when: str) -> None:
        now = self._clock()
        span = window(when, now)
        if isinstance(span, Ask):
            await self._say(message, chat_id, span.question)
            return
        start, end, label = span
        reading = await asyncio.to_thread(self._agenda.read, start, end)
        await message.reply_text(listing(reading.items, label, now, reading.failed))
        self._assistant.remember(chat_id, f"(Mostrei a agenda de {label}.)")

    # --- creating -------------------------------------------------------------------------------------------

    async def _create(self, message, chat_id: int, action: Action, user_text: str) -> None:
        now = self._clock()
        if action.ref == FORCED:  # approved after "já há algo nesse horário": nothing left to ask
            account = next((a for a in self._agenda.accounts if a.key == action.conta), None)
            start = datetime.fromisoformat(action.quando)
            if account is None:
                await self._say(message, chat_id, account_question(self._agenda.accounts))
                return
            await self._insert(message, chat_id, Plan(account, action.texto, start,
                                                      start + timedelta(minutes=action.duracao), False))
            return
        said = user_text or f"{action.texto} {action.quando}"
        result = self._flow.start(chat_id, said, action.texto, action.quando, action.duracao, action.conta, now)
        await self._after_plan(message, chat_id, result)

    async def _after_plan(self, message, chat_id: int, result: Plan | Ask) -> None:
        if isinstance(result, Ask):
            await self._say(message, chat_id, result.question)
            return
        try:
            clash = await asyncio.to_thread(self._agenda.clashes, result)
        except CalendarError as exc:
            await self._say(message, chat_id, _failure(exc))
            return
        if clash.items:
            what = "; ".join(f"“{c.event.title}” ({_span_of(c)})" for c in clash.items[:3])
            question = (f"Já há {what} nesse horário, senhor. Marco “{result.title}” mesmo assim? "
                        f"Diga \"sim\" para confirmar.")
            self._assistant.offer(chat_id, Action(
                "criar_evento", texto=result.title, quando=result.start.isoformat(),
                duracao=int((result.end - result.start).total_seconds() // 60), conta=result.account.key, ref=FORCED))
            await self._say(message, chat_id, question)
            return
        await self._insert(message, chat_id, result)

    async def _insert(self, message, chat_id: int, plan: Plan) -> None:
        event_id = new_event_id()
        try:
            await asyncio.to_thread(self._agenda.create, plan, event_id)
        except CalendarError as exc:
            await self._say(message, chat_id, _failure(exc))
            return
        now = self._clock()
        minutes = int((plan.end - plan.start).total_seconds() // 60)
        length = f"{minutes // 60} h" if minutes % 60 == 0 else f"{minutes} min"
        text = (f"Marcado, senhor: “{plan.title}”, {describe_span(plan, now)}, na agenda {plan.account.label}."
                + (f" Como o senhor não disse a duração, deixei {length}." if plan.assumed_length else ""))
        undo = InlineKeyboardMarkup([[InlineKeyboardButton("Desfazer", callback_data=f"{UNDO_PREFIX}:{plan.account.key}:{event_id}")]])
        await self._say(message, chat_id, text, markup=undo)

    async def undo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """The “Desfazer” button under a new event."""
        query = update.callback_query
        _, key, event_id = query.data.split(":", 2)
        account = next((a for a in self._agenda.accounts if a.key == key), None)
        if account is None:
            await query.answer("Agenda desconhecida.")
            return
        try:
            await asyncio.to_thread(self._agenda.delete, f"{key}:{event_id}")
        except CalendarError as exc:
            await query.answer(_failure(exc)[:190], show_alert=True)
            return
        await query.answer("Desfeito, senhor.")
        await query.edit_message_text(query.message.text + "\n\n↩ Desfeito: evento apagado.")

    # --- moving and cancelling ------------------------------------------------------------------------------

    async def _find_one(self, message, chat_id: int, words: str) -> Shown | None:
        try:
            found = await asyncio.to_thread(self._agenda.find, words)
        except CalendarError as exc:
            await self._say(message, chat_id, _failure(exc))
            return None
        if not found.items:
            note = f" Não consegui ler: {', '.join(a.label for a in found.failed)}." if found.failed else ""
            await self._say(message, chat_id, NOT_FOUND + note)
            return None
        if len(found.items) > 1:
            shown = found.items[:MAX_LIST]
            await self._say(message, chat_id, "Encontrei mais de um, senhor. Diga mais palavras do título:\n\n" + _numbered(shown))
            return None
        return found.items[0]

    async def _propose_cancel(self, message, chat_id: int, action: Action) -> None:
        item = await self._find_one(message, chat_id, action.busca)
        if item is None:
            return
        where = " e ".join(a.label for a in item.accounts)
        self._assistant.offer(chat_id, Action("cancelar_evento", texto=item.event.title, ref=item.ref))
        await self._say(message, chat_id, f"Apago “{item.event.title}” ({describe(item.event, self._clock())}, "
                                          f"agenda {where}), senhor? Diga \"sim\" para confirmar.")

    async def _do_cancel(self, message, chat_id: int, action: Action) -> None:
        failed = await asyncio.to_thread(self._agenda.delete, action.ref)
        text = f"Apagado, senhor: “{action.texto}”."
        if failed:
            text += f" Não consegui apagar na agenda {', '.join(a.label for a in failed)}."
        await self._say(message, chat_id, text)

    async def _propose_move(self, message, chat_id: int, action: Action, user_text: str) -> None:
        item = await self._find_one(message, chat_id, action.busca)
        if item is None:
            return
        now = self._clock()
        # the new moment is read from the owner's words (the model drops details), like a reminder's
        planned = plan_from_words(user_text or action.quando, action.busca, action.quando, 0, now, ask_repeat=False)
        if isinstance(planned, Ask):
            await self._say(message, chat_id, planned.question)
            return
        if not isinstance(planned, Planned) or planned.repeat:
            await self._say(message, chat_id, "Diga um dia e uma hora só, senhor.")
            return
        length = int((item.event.end - item.event.start).total_seconds() // 60)
        where = " e ".join(a.label for a in item.accounts)
        self._assistant.offer(chat_id, Action("mover_evento", texto=item.event.title, quando=planned.due.isoformat(),
                                              duracao=length, ref=item.ref))
        await self._say(message, chat_id, f"Movo “{item.event.title}” de {describe(item.event, now)} para "
                                          f"{describe_span_start(planned.due, length, now)} (agenda {where}), senhor? "
                                          f"Diga \"sim\" para confirmar.")

    async def _do_move(self, message, chat_id: int, action: Action, user_text: str) -> None:
        start = datetime.fromisoformat(action.quando)
        failed = await asyncio.to_thread(self._agenda.move, action.ref, start, start + timedelta(minutes=action.duracao))
        text = f"Remarcado, senhor: “{action.texto}” agora é {describe_span_start(start, action.duracao, self._clock())}."
        if failed:
            text += f" Não consegui mudar na agenda {', '.join(a.label for a in failed)}."
        await self._say(message, chat_id, text)


def _span_of(item: Shown) -> str:
    return item.event.start.strftime("%H:%M") + "–" + item.event.end.strftime("%H:%M")


def describe_span_start(start: datetime, minutes: int, now: datetime) -> str:
    end = start + timedelta(minutes=minutes)
    return f"{day_time(start, now)} até {end:%H:%M}"


def describe_span(plan: Plan, now: datetime) -> str:
    return describe_span_start(plan.start, int((plan.end - plan.start).total_seconds() // 60), now)
