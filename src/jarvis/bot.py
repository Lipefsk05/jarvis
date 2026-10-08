"""Telegram front-end: a thin wrapper over Assistant. Only allowlisted users get answers."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from .assistant import Assistant
from .budget import Budget
from .commands import parse_note_request, task_query_words
from .config import Settings
from .conversation import History
from .humor import HumorGate
from .inbox import write_note
from .mind import load_pending, resolve_query, select
from .telegram_format import format_items, format_summary, safe
from .persona import load_template
from .talker.factory import build_talker

log = logging.getLogger("jarvis")

GREETING = (
    "À disposição, senhor. Por ora eu converso, anoto no seu Mind e consulto as tarefas pendentes: "
    "/anota <texto> guarda uma nota, /tarefas [área] mostra as pendências, /uso mostra o gasto do dia "
    "e /esquece limpa a conversa."
)
UNKNOWN_COMMAND = "Não conheço esse comando, senhor. Use /anota, /tarefas, /uso ou /esquece."
TASK_LIST_LIMIT = 20  # Telegram messages cap at 4096 characters
NOT_FUNNY = "not_funny"


def feedback_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("😐 essa não deu", callback_data=NOT_FUNNY)]]
    )


def build_application(settings: Settings) -> Application:
    tz = ZoneInfo(settings.timezone)

    def clock() -> datetime:
        return datetime.now(tz)

    budget = Budget(
        settings.state_dir / "usage.json",
        settings.daily_budget_usd,
        settings.price_in,
        settings.price_out,
        clock=clock,
    )
    gate = HumorGate()
    history = History(settings.history_messages)
    assistant = Assistant(
        talker=build_talker(settings),
        budget=budget,
        gate=gate,
        history=history,
        template=load_template(settings.persona_path),
        clock=clock,
        estado_path=settings.state_dir / "estado_atual.md",
        mind_dir=settings.mind_dir,
    )
    allowed = filters.User(user_id=list(settings.allowed_ids))

    async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(GREETING)

    async def save_note(message, text: str) -> None:
        if not text:
            await message.reply_text("O que devo anotar, senhor? Use /anota <texto>.")
            return
        path = await asyncio.to_thread(write_note, settings.inbox_dir, text, clock(), "telegram")
        await message.reply_text(f"Anotado, senhor ({path.name}).")

    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat_id = update.effective_chat.id
        note = parse_note_request(message.text)
        if note is not None:  # handled by code: no model call, nothing to invent
            await save_note(message, note)
            return
        await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
        reply = await asyncio.to_thread(assistant.respond, chat_id, message.text)
        markup = feedback_markup() if reply.humor_offered else None
        await message.reply_text(reply.text, reply_markup=markup)
        if reply.provider and reply.provider != settings.provider:
            await message.reply_text(f"↪ respondido pelo provedor reserva ({reply.provider}).")
        if reply.warn_budget:
            await message.reply_text("Aviso, senhor: já usei 80% do teto de gasto de hoje.")

    async def on_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        await save_note(message, message.text.partition(" ")[2].strip())

    async def on_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        typed = task_query_words(" ".join(context.args or []), min_len=3)
        tasks = await asyncio.to_thread(load_pending, settings.mind_dir)
        words, fixes = resolve_query(tasks, typed)  # tolerate typos, but only in an explicit query
        chosen = select(tasks, words)
        understood = "".join(f"Entendi “{safe(a)}” como “{safe(b)}”.\n" for a, b in fixes)
        understood = f"{understood}\n" if understood else ""
        opts = {"parse_mode": ParseMode.HTML, "link_preview_options": LinkPreviewOptions(is_disabled=True)}
        if chosen:
            await message.reply_text(understood + format_items(chosen, TASK_LIST_LIMIT), **opts)
        elif words:
            await message.reply_text(
                f"Não encontrei pendências para \"{safe(' '.join(words))}\", senhor.\n\n{format_summary(tasks)}", **opts
            )
        else:
            await message.reply_text(format_summary(tasks), **opts)

    async def on_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(UNKNOWN_COMMAND)

    async def on_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(budget.summary())

    async def on_forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        history.clear(update.effective_chat.id)
        await update.effective_message.reply_text("Conversa limpa, senhor.")

    async def on_not_funny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query.from_user.id not in settings.allowed_ids:
            await query.answer()
            return
        gate.feedback_not_funny(query.message.chat_id)
        settings.state_dir.mkdir(parents=True, exist_ok=True)
        entry = {"ts": clock().isoformat(timespec="seconds"), "reply": query.message.text}
        with (settings.state_dir / "humor_feedback.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        await query.answer("Anotado, senhor.")
        await query.edit_message_reply_markup(reply_markup=None)

    async def on_any(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        kind = "callback" if update.callback_query else ("message" if update.effective_message else "other")
        log.info("Update received: kind=%s user_id=%s allowed=%s", kind,
                 user.id if user else "?", bool(user and user.id in settings.allowed_ids))

    async def on_stranger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        log.warning("Ignored message from non-allowlisted user id=%s", user.id if user else "?")

    app = Application.builder().token(settings.telegram_token).build()
    app.add_handler(TypeHandler(Update, on_any), group=-1)  # logs ids only, never content
    app.add_handler(CommandHandler("start", on_start, filters=allowed))
    app.add_handler(CommandHandler("anota", on_note, filters=allowed))
    app.add_handler(CommandHandler("uso", on_usage, filters=allowed))
    app.add_handler(CommandHandler("tarefas", on_tasks, filters=allowed))
    app.add_handler(CommandHandler(["esquece", "esquecer"], on_forget, filters=allowed))
    app.add_handler(MessageHandler(allowed & filters.COMMAND, on_unknown))
    app.add_handler(MessageHandler(allowed & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_not_funny, pattern=f"^{NOT_FUNNY}$"))
    app.add_handler(MessageHandler(~allowed, on_stranger), group=1)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs full request URLs at INFO, and Telegram URLs contain the bot token.
    for noisy in ("httpx", "httpcore", "telegram"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    settings = Settings.load()
    problems = settings.problems()
    if problems:
        print("Cannot start. Fix your .env first:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        sys.exit(1)

    log.info(
        "Starting Jarvis: provider=%s model=%s allowed_users=%d",
        settings.provider, settings.model, len(settings.allowed_ids),
    )
    build_application(settings).run_polling(allowed_updates=Update.ALL_TYPES)
