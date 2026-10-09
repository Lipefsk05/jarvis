"""Telegram front-end: a thin wrapper over Assistant. Only allowlisted users get answers."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Update
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
from .commands import asks_capabilities, parse_note_request, task_query_words, wants_tasks
from .help import format_help, menu
from .config import Settings
from .conversation import History
from .humor import HumorGate
from .inbox import write_note
from .mind import load_pending, resolve_query, select
from .telegram_format import format_items, format_summary, safe
from .usage import format_usage
from .persona import load_template
from .talker.factory import build_talker

log = logging.getLogger("jarvis")

GREETING = "À disposição, senhor. Eu converso, anoto no seu Mind e consulto as tarefas pendentes. Use /ajuda para ver tudo o que sei fazer."
UNKNOWN_COMMAND = "Não conheço esse comando, senhor. Use /ajuda para ver o que sei fazer."
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
    history = History(settings.history_messages, settings.state_dir / "conversa.json")
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

    async def run_action(message, chat_id: int, action) -> None:
        """Execute what the model asked for. The text sent back is produced here, not by the model."""
        if action.name == "anotar":
            path = await asyncio.to_thread(write_note, settings.inbox_dir, action.texto, clock(), "telegram")
            preview = action.texto if len(action.texto) <= 80 else action.texto[:77] + "…"
            confirmation = f"Anotado, senhor: “{preview}” ({path.name})."
            await message.reply_text(confirmation)
            assistant.remember(chat_id, confirmation)
        elif action.name == "consultar_tarefas":
            await reply_tasks(message, task_query_words(action.area, min_len=3))
            assistant.remember(chat_id, "(Mostrei as pendências" + (f" de {action.area}" if action.area else "") + ".)")
        elif action.name == "ver_gasto":
            await send_usage(message)
            assistant.remember(chat_id, "(Mostrei o uso de hoje.)")
        elif action.name == "mostrar_ajuda":
            await send_help(message)
            assistant.remember(chat_id, "(Mostrei a lista do que sei fazer.)")
        elif action.name == "limpar_conversa":
            history.clear(chat_id)
            await message.reply_text("Conversa limpa, senhor.")

    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat_id = update.effective_chat.id
        note = parse_note_request(message.text)
        if note is not None:  # handled by code: no model call, nothing to invent
            await save_note(message, note)
            return
        if asks_capabilities(message.text):  # the list comes from code, so it is always complete and right
            await send_help(message)
            return
        if wants_tasks(message.text):  # same readable answer as /tarefas, no model call
            await reply_tasks(message, task_query_words(message.text))
            return
        await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
        reply = await asyncio.to_thread(assistant.respond, chat_id, message.text)
        if reply.action is not None:
            await run_action(message, chat_id, reply.action)
        else:
            markup = feedback_markup() if reply.humor_offered else None
            await message.reply_text(reply.text, reply_markup=markup)
        if reply.provider and reply.provider != settings.provider:
            await message.reply_text(f"↪ respondido pelo provedor reserva ({reply.provider}).")
        if reply.warn_budget:
            await message.reply_text("Aviso, senhor: já usei 80% do teto de gasto de hoje.")

    async def on_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        await save_note(message, message.text.partition(" ")[2].strip())

    async def reply_tasks(message, typed: list[str]) -> None:
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

    async def send_help(message) -> None:
        await message.reply_text(
            format_help(), parse_mode=ParseMode.HTML, link_preview_options=LinkPreviewOptions(is_disabled=True)
        )

    async def on_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await send_help(update.effective_message)

    async def on_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply_tasks(update.effective_message, task_query_words(" ".join(context.args or []), min_len=3))

    async def on_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(UNKNOWN_COMMAND)

    async def send_usage(message) -> None:
        await message.reply_text(
            format_usage(budget.report(), assistant.provider_info()),
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    async def on_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await send_usage(update.effective_message)

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

    async def publish_menu(application: Application) -> None:
        try:
            await application.bot.set_my_commands([BotCommand(name, text) for name, text in menu()])
        except Exception as exc:  # the menu is a convenience; the bot works without it
            log.warning("Could not publish the command menu: %s", type(exc).__name__)

    app = Application.builder().token(settings.telegram_token).post_init(publish_menu).build()
    app.add_handler(TypeHandler(Update, on_any), group=-1)  # logs ids only, never content
    app.add_handler(CommandHandler("start", on_start, filters=allowed))
    app.add_handler(CommandHandler("anota", on_note, filters=allowed))
    app.add_handler(CommandHandler("uso", on_usage, filters=allowed))
    app.add_handler(CommandHandler("tarefas", on_tasks, filters=allowed))
    app.add_handler(CommandHandler(["ajuda", "help"], on_help, filters=allowed))
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
