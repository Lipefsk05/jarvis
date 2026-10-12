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
from .audio import GroqTranscriber, TranscribeError, check_audio, transcript_line
from .budget import Budget
from .commands import asks_capabilities, parse_note_request, parse_reminder_request, task_query_words, wants_tasks
from .help import format_help, menu
from .config import Settings
from .conversation import History
from . import heartbeat, scheduler
from .humor import HumorGate
from .inbox import NoteJournal, write_note
from .mind import load_pending, resolve_query, select
from .outbox import Outbox, TelegramChannel
from .reminder_flow import Dropped, ReminderFlow
from .reminder_request import PlannedSeries, is_schedule
from .reminder_text import confirmation, listing, series_confirmation
from .reminders import ReminderError, ReminderStore
from .when import Ask
from .telegram_format import format_items, format_summary, safe
from .usage import format_usage
from .persona import load_template
from .talker.factory import build_talker

log = logging.getLogger("jarvis")

GREETING = "À disposição, senhor. Eu converso, anoto no seu Mind e consulto as tarefas pendentes. Use /ajuda para ver tudo o que sei fazer."
UNSUPPORTED_MEDIA = "Por ora só entendo texto e áudio, senhor. Fotos, arquivos e figurinhas eu ainda não sei tratar."
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
    reminders = ReminderStore(settings.state_dir / "lembretes.json")
    flow = ReminderFlow()
    notes = NoteJournal(settings.state_dir / "notas_recentes.json")
    owner_chat = min(settings.allowed_ids)  # proactive messages go to the owner's private chat
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
    transcriber = GroqTranscriber(settings.groq_api_key) if settings.groq_api_key else None
    allowed = filters.User(user_id=list(settings.allowed_ids))

    async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(GREETING)

    async def save_note(message, text: str) -> None:
        if not text:
            await message.reply_text("O que devo anotar, senhor? Use /anota <texto>.")
            return
        path = await asyncio.to_thread(write_note, settings.inbox_dir, text, clock(), "telegram")
        notes.add(path)
        await message.reply_text(f"Anotado, senhor ({path.name}).")

    async def undo_note(message, chat_id: int) -> None:
        undone = await asyncio.to_thread(notes.undo_last, settings.inbox_dir)
        if undone is None:
            reply = "Não há nota minha para desfazer, senhor."
        elif undone[1] is None:
            reply = f"A nota {undone[0]} já não está no inbox, senhor (talvez já tenha sido integrada ao Mind). Nada a desfazer."
        else:
            preview = undone[1] if len(undone[1]) <= 80 else undone[1][:77] + "…"
            reply = f"Nota desfeita, senhor: “{preview}” ({undone[0]})."
        await message.reply_text(reply)
        assistant.remember(chat_id, reply)

    async def run_action(message, chat_id: int, action, user_text: str = "") -> None:
        """Execute what the model asked for. The text sent back is produced here, not by the model.
        `user_text` is what the user wrote, when the model decided the action by itself (not after a \"yes\")."""
        if action.name == "anotar":
            path = await asyncio.to_thread(write_note, settings.inbox_dir, action.texto, clock(), "telegram")
            notes.add(path)
            preview = action.texto if len(action.texto) <= 80 else action.texto[:77] + "…"
            confirmation = f"Anotado, senhor: “{preview}” ({path.name})."
            await message.reply_text(confirmation)
            assistant.remember(chat_id, confirmation)
        elif action.name == "consultar_tarefas":
            await reply_tasks(message, task_query_words(action.area, min_len=3))
            assistant.remember(chat_id, "(Mostrei as pendências" + (f" de {action.area}" if action.area else "") + ".)")
        elif action.name == "criar_lembrete":
            # The user's own words give the day and the hour (the model drops details); the model only gives the text.
            # After a "yes" to an offer there are no words to read, so the model's `quando` is the user's request.
            said = user_text or action.quando + (f", {action.antecedencia} min antes" if action.antecedencia else "")
            planned = flow.start(chat_id, said, clock(), text=action.texto, when=action.quando, lead=action.antecedencia)
            await store_reminder(message, chat_id, planned)
        elif action.name == "listar_lembretes":
            await message.reply_text(listing(reminders.pending(), clock()))
            assistant.remember(chat_id, "(Mostrei os lembretes pendentes.)")
        elif action.name == "cancelar_lembrete":
            await cancel_reminder(message, chat_id, action.numero, action.busca)
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
        await handle_text(update.effective_message, update.effective_chat.id, update.effective_message.text, context)

    async def handle_text(message, chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE) -> None:
        """One user turn, typed or transcribed from audio: shortcuts handled by code first, then the model."""
        confirmed = assistant.confirm_offer(chat_id, text)
        if confirmed is not None:  # "sim" to a reminder the code proposed: no model, exact data
            await run_action(message, chat_id, confirmed)
            return
        answered = flow.answer(chat_id, text, clock())  # a question about a reminder is waiting for this message
        if answered is not None:
            await store_reminder(message, chat_id, answered)
            return
        note = parse_note_request(text)
        if note is not None:  # handled by code: no model call, nothing to invent
            await save_note(message, note)
            return
        remind = parse_reminder_request(text)
        if remind is not None:  # "me lembra de ..." is handled by code too: validated date, no invention
            await create_reminder(message, chat_id, remind)
            return
        if is_schedule(text):  # "toda terça e sexta academia às 15": a repeat and an hour are a request, no model needed
            await create_reminder(message, chat_id, text)
            return
        if asks_capabilities(text):  # the list comes from code, so it is always complete and right
            await send_help(message)
            return
        if wants_tasks(text):  # same readable answer as /tarefas, no model call
            await reply_tasks(message, task_query_words(text))
            return
        await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
        reply = await asyncio.to_thread(assistant.respond, chat_id, text)
        if reply.action is not None:
            await run_action(message, chat_id, reply.action, text)
        else:
            markup = feedback_markup() if reply.humor_offered else None
            await message.reply_text(reply.text, reply_markup=markup)
        if reply.provider and reply.provider != settings.provider:
            await message.reply_text(f"↪ respondido pelo provedor reserva ({reply.provider}).")
        if reply.warn_budget:
            await message.reply_text("Aviso, senhor: já usei 80% do teto de gasto de hoje.")

    async def on_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Voice note or audio file: transcribe, show what was understood, then treat it like typed text."""
        message = update.effective_message
        chat_id = update.effective_chat.id
        media = message.voice or message.audio
        if transcriber is None:
            await message.reply_text("Não consigo transcrever áudio, senhor: falta a chave do Groq.")
            return
        refusal = check_audio(media.duration, media.file_size)
        if refusal:
            await message.reply_text(refusal)
            return
        await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
        try:
            file = await context.bot.get_file(media.file_id)
            data = bytes(await file.download_as_bytearray())
            text = await asyncio.to_thread(transcriber.transcribe, getattr(media, "file_name", None) or "voz.ogg", data)
        except TranscribeError as exc:
            await message.reply_text(exc.reason)
            return
        except Exception as exc:  # download failed: say so instead of staying silent
            log.warning("Audio download failed: %s", type(exc).__name__)
            await message.reply_text("Não consegui baixar o áudio, senhor.")
            return
        await message.reply_text(transcript_line(text))
        await handle_text(message, chat_id, text, context)

    async def on_unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(UNSUPPORTED_MEDIA)

    REMIND_USAGE = (
        "Diga quando e o quê, senhor. Ex.: /lembra amanhã às 9 pagar o aluguel, "
        "/lembra hoje às 19 reunião, 10 min antes, ou /lembra daqui a 2 horas tirar o bolo."
    )

    async def store_reminder(message, chat_id: int, planned) -> None:
        """Store a planned reminder (or relay the question) and confirm in the code's own words."""
        now = clock()
        if isinstance(planned, Ask):
            await message.reply_text(planned.question)
            assistant.remember(chat_id, planned.question)  # so a later "sim" or "às 8" is read in context
            return
        if isinstance(planned, Dropped):
            await message.reply_text(planned.message)
            return
        if isinstance(planned, PlannedSeries):
            await store_series(message, chat_id, planned)
            return
        try:
            reminder = reminders.add(planned.text, planned.due, now, event=planned.event, repeat=planned.repeat)
        except ReminderError as exc:
            await message.reply_text(str(exc))
            return
        text = confirmation(reminder, now, planned.hour_assumed)
        await message.reply_text(text)
        assistant.remember(chat_id, text)

    async def store_series(message, chat_id: int, series: PlannedSeries) -> None:
        """"Toda segunda e quarta": one weekly reminder per day, one confirmation."""
        now = clock()
        stored = []
        try:
            for planned in series.items:
                stored.append(reminders.add(planned.text, planned.due, now, event=planned.event, repeat=planned.repeat))
        except ReminderError as exc:
            for reminder in stored:  # all or nothing: do not leave half of the days marked
                reminders.cancel(reminder.id, now)
            await message.reply_text(str(exc))
            return
        text = series_confirmation(stored, now, any(p.hour_assumed for p in series.items))
        await message.reply_text(text)
        assistant.remember(chat_id, text)

    async def create_reminder(message, chat_id: int, raw: str) -> None:
        if not raw:
            await message.reply_text(REMIND_USAGE)
            return
        await store_reminder(message, chat_id, flow.start(chat_id, raw, clock()))

    async def cancel_reminder(message, chat_id: int, numero: int, busca: str) -> None:
        if not numero:
            found = reminders.search(busca)
            if not found:
                await message.reply_text(f"Não encontrei lembrete pendente com “{busca}”, senhor.")
                return
            if len(found) > 1:
                await message.reply_text("Encontrei mais de um, senhor. Diga o número:\n\n" + listing(found, clock()))
                return
            numero = found[0].id
        cancelled = reminders.cancel(numero, clock())
        if cancelled is None:
            await message.reply_text(f"Não encontrei o lembrete {numero} entre os pendentes, senhor.")
            return
        text = f"Lembrete {cancelled.id} cancelado, senhor: {cancelled.text}." + (" Não repito mais." if cancelled.repeat else "")
        await message.reply_text(text)
        assistant.remember(chat_id, text)

    async def on_remind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        await create_reminder(message, update.effective_chat.id, message.text.partition(" ")[2].strip())

    async def on_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(listing(reminders.pending(), clock()))

    async def on_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        arg = message.text.partition(" ")[2].strip().lstrip("#")
        if not arg.isdigit():
            await message.reply_text("Qual lembrete, senhor? Informe o número.\n\n" + listing(reminders.pending(), clock()))
            return
        await cancel_reminder(message, update.effective_chat.id, int(arg), "")

    async def on_undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await undo_note(update.effective_message, update.effective_chat.id)

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
        outage = context.application.bot_data.get("outage")
        message = update.effective_message
        if outage and message and user and user.id in settings.allowed_ids and message.date < outage.end:
            context.application.bot_data.pop("outage")  # announce once, only when a message waited for us
            await message.reply_text(
                f"Estive fora do ar {outage.describe()}, senhor. A sua mensagem ficou na fila e só chegou agora."
            )
        kind = "callback" if update.callback_query else ("message" if update.effective_message else "other")
        log.info("Update received: kind=%s user_id=%s allowed=%s", kind,
                 user.id if user else "?", bool(user and user.id in settings.allowed_ids))

    async def on_stranger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        log.warning("Ignored message from non-allowlisted user id=%s", user.id if user else "?")

    async def start_heartbeat(application: Application) -> None:
        beat_path = settings.state_dir / "heartbeat"
        outage = heartbeat.find_outage(heartbeat.read_last(beat_path), clock())
        if outage:
            log.warning("Was down %s", outage.describe())
            application.bot_data["outage"] = outage
        application.bot_data["heartbeat"] = asyncio.create_task(heartbeat.run(beat_path, clock))

    async def start_scheduler(application: Application) -> None:
        outbox = Outbox([TelegramChannel(application.bot, owner_chat)])
        application.bot_data["scheduler"] = asyncio.create_task(scheduler.run(
            reminders, outbox, clock, on_delivered=lambda text: assistant.remember(owner_chat, text),
        ))

    async def publish_menu(application: Application) -> None:
        try:
            await application.bot.set_my_commands([BotCommand(name, text) for name, text in menu()])
        except Exception as exc:  # the menu is a convenience; the bot works without it
            log.warning("Could not publish the command menu: %s", type(exc).__name__)

    async def post_init(application: Application) -> None:
        await publish_menu(application)
        await start_heartbeat(application)
        await start_scheduler(application)

    async def post_shutdown(application: Application) -> None:
        for name in ("heartbeat", "scheduler"):
            task = application.bot_data.get(name)
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    app = Application.builder().token(settings.telegram_token).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(TypeHandler(Update, on_any), group=-1)  # logs ids only, never content
    app.add_handler(CommandHandler("start", on_start, filters=allowed))
    app.add_handler(CommandHandler("anota", on_note, filters=allowed))
    app.add_handler(CommandHandler(["desfaz", "desfazer"], on_undo, filters=allowed))
    app.add_handler(CommandHandler("lembra", on_remind, filters=allowed))
    app.add_handler(CommandHandler("lembretes", on_reminders, filters=allowed))
    app.add_handler(CommandHandler("cancela", on_cancel, filters=allowed))
    app.add_handler(CommandHandler("uso", on_usage, filters=allowed))
    app.add_handler(CommandHandler("tarefas", on_tasks, filters=allowed))
    app.add_handler(CommandHandler(["ajuda", "help"], on_help, filters=allowed))
    app.add_handler(CommandHandler(["esquece", "esquecer"], on_forget, filters=allowed))
    app.add_handler(MessageHandler(allowed & filters.COMMAND, on_unknown))
    app.add_handler(MessageHandler(allowed & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(allowed & (filters.VOICE | filters.AUDIO), on_audio))
    app.add_handler(MessageHandler(
        allowed & (filters.PHOTO | filters.VIDEO | filters.VIDEO_NOTE | filters.Document.ALL | filters.Sticker.ALL
                   | filters.ANIMATION | filters.LOCATION | filters.CONTACT | filters.POLL),
        on_unsupported,
    ))
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
