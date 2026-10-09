"""Orchestrates one conversational turn: budget, humor gate, persona, model, history."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .actions import TOOLS, Action, parse_action
from .budget import Budget
from .commands import has_reminder_intent, is_yes, task_query_words, wants_tasks
from .conversation import History
from .humor import HumorGate
from .mind import tasks_context
from .persona import render
from .style import StyleHints
from .talker.base import Talker, TalkerError

log = logging.getLogger(__name__)

OFFER_TTL = timedelta(minutes=10)  # how long a "want me to remind you?" stays open
BLOCKED_MESSAGE = (
    "Atingi o teto de gasto de hoje, senhor. Volto a conversar amanhã, "
    "ou assim que o senhor liberar o limite."
)
FAILED_MESSAGE = "Não consegui falar com o modelo agora, senhor. Tente de novo em instantes."
# The model writes the joke itself inside a tag, "[[humor: the joke]]". The tag is
# unwrapped (the joke stays in the text), and it only counts as a joke when real text
# is inside: models like to append a bare "[[humor]]" as a ritual, which must not
# trigger the feedback button or start the cooldown.
_JOKE_TAG_RE = re.compile(r"\[{1,2}\s*humor\s*(?::\s*(.*?))?\s*\]{1,2}", re.IGNORECASE | re.DOTALL)
_STRAY_CLOSER_RE = re.compile(r"\s*\]\]\s*$")
MIN_JOKE_WORDS = 3


def split_joke(text: str) -> tuple[str, bool]:
    """Return (clean text, whether a real joke was inside a humor tag)."""
    jokes: list[str] = []

    def unwrap(match: re.Match) -> str:
        inner = (match.group(1) or "").strip()
        if len(inner.split()) >= MIN_JOKE_WORDS:
            jokes.append(inner)
            before = match.string[match.start() - 1] if match.start() > 0 else " "
            return inner if before.isspace() else " " + inner
        return ""

    clean = _JOKE_TAG_RE.sub(unwrap, text)
    clean = _STRAY_CLOSER_RE.sub("", clean)
    clean = re.sub(r"[ \t]{2,}", " ", clean).strip()
    return clean, bool(jokes)


@dataclass(frozen=True)
class AssistantReply:
    text: str
    humor_offered: bool = False
    warn_budget: bool = False
    blocked: bool = False
    provider: str = ""
    action: Action | None = None  # the model asked the system to do something instead of answering


class Assistant:
    def __init__(
        self,
        *,
        talker: Talker,
        budget: Budget,
        gate: HumorGate,
        history: History,
        template: str,
        clock: Callable[[], datetime],
        estado_path: Path | None = None,
        mind_dir: Path | None = None,
        hints: StyleHints | None = None,
        tools: list[dict] | None = None,
    ) -> None:
        self._talker = talker
        self._budget = budget
        self._gate = gate
        self._history = history
        self._template = template
        self._clock = clock
        self._estado_path = estado_path
        self._mind_dir = mind_dir
        self._hints = hints or StyleHints()
        self._tools = TOOLS if tools is None else tools
        self._offers: dict[int, tuple[datetime, Action]] = {}  # reminder proposals waiting for a "yes"

    def confirm_offer(self, chat_id: int, text: str) -> Action | None:
        """If a reminder was proposed and this message is a plain yes, return the proposed action.
        Any other message closes the offer. The code keeps the offer, so a yes needs no model."""
        offer = self._offers.pop(chat_id, None)
        if offer is None:
            return None
        made, action = offer
        if self._clock() - made > OFFER_TTL or not is_yes(text):
            return None
        self._history.add(chat_id, "user", text)
        return action

    def _estado_atual(self) -> str:
        if self._estado_path is None:
            return ""
        try:
            return self._estado_path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def provider_info(self) -> list[dict]:
        """Which providers are in the chain (empty if the talker does not describe itself)."""
        info = getattr(self._talker, "info", None)
        return info() if callable(info) else []

    def remember(self, chat_id: int, text: str) -> None:
        """Record what the system answered for an action, so later turns know it happened."""
        self._history.add(chat_id, "assistant", text)

    def _reminder_wanted(self, chat_id: int, text: str) -> bool:
        """True if this message asks for a reminder, or says yes to a reminder the assistant just offered.
        An offer is a question about reminders; a confirmation like "Lembrete 8 cancelado" is not one."""
        if has_reminder_intent(text):
            return True
        history = self._history.messages(chat_id)
        previous = history[-2] if len(history) >= 2 else None
        return bool(
            previous and previous["role"] == "assistant"
            and "?" in previous["content"] and has_reminder_intent(previous["content"])
        )

    def _tasks(self, text: str) -> str:
        if self._mind_dir is None or not wants_tasks(text):
            return ""
        try:
            return tasks_context(self._mind_dir, task_query_words(text))
        except OSError:
            return "(não consegui ler as tarefas do Mind agora)"

    def respond(self, chat_id: int, text: str) -> AssistantReply:
        if not self._budget.can_spend():
            return AssistantReply(BLOCKED_MESSAGE, blocked=True)

        permitted = self._gate.permitted(chat_id, text)
        system = render(
            self._template,
            humor_allowed=permitted,
            now=self._clock(),
            estado_atual=self._estado_atual(),
            tarefas=self._tasks(text),
            dica=self._hints.hint_for(chat_id, text),
        )
        self._history.add(chat_id, "user", text)
        try:
            reply = self._talker.reply(system, self._history.messages(chat_id), self._tools or None)
        except TalkerError as exc:
            log.warning("Talker failed: %s", exc)
            self._history.drop_last(chat_id)
            return AssistantReply(FAILED_MESSAGE)

        self._budget.add(reply.input_tokens, reply.output_tokens, reply.cost_usd, reply.provider)
        action = parse_action(reply.tool_call)
        if action is not None and action.name == "criar_lembrete" and not self._reminder_wanted(chat_id, text):
            # The model decided on its own; the user only mentioned something. Ask instead of creating it.
            question = f'Quer que eu o avise disso, senhor? Diga "sim" e eu marco para {action.quando}.'
            self._offers[chat_id] = (self._clock(), action)
            self._history.add(chat_id, "assistant", question)
            return AssistantReply(question, provider=reply.provider)
        if action is not None:  # the system answers; any text the model also wrote is dropped
            return AssistantReply("", provider=reply.provider, action=action)
        clean, joked = split_joke(reply.text)
        if not clean:
            self._history.drop_last(chat_id)
            return AssistantReply(FAILED_MESSAGE)
        if joked:
            if not permitted:
                log.warning("Model joked while humor was not permitted")
            self._gate.record_joke(chat_id)
        self._history.add(chat_id, "assistant", clean)
        return AssistantReply(
            clean,
            humor_offered=joked,
            warn_budget=self._budget.should_warn(),
            provider=reply.provider,
        )
