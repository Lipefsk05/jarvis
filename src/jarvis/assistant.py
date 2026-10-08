"""Orchestrates one conversational turn: budget, humor gate, persona, model, history."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .budget import Budget
from .conversation import History
from .humor import HumorGate
from .persona import render
from .talker.base import Talker, TalkerError

log = logging.getLogger(__name__)

BLOCKED_MESSAGE = (
    "Atingi o teto de gasto de hoje, senhor. Volto a conversar amanhã, "
    "ou assim que o senhor liberar o limite."
)
FAILED_MESSAGE = "Não consegui falar com o modelo agora, senhor. Tente de novo em instantes."


@dataclass(frozen=True)
class AssistantReply:
    text: str
    humor_offered: bool = False
    warn_budget: bool = False
    blocked: bool = False


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
    ) -> None:
        self._talker = talker
        self._budget = budget
        self._gate = gate
        self._history = history
        self._template = template
        self._clock = clock
        self._estado_path = estado_path

    def _estado_atual(self) -> str:
        if self._estado_path is None:
            return ""
        try:
            return self._estado_path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def respond(self, chat_id: int, text: str) -> AssistantReply:
        if not self._budget.can_spend():
            return AssistantReply(BLOCKED_MESSAGE, blocked=True)

        humor = self._gate.decide(chat_id, text)
        system = render(
            self._template,
            humor_allowed=humor,
            now=self._clock(),
            estado_atual=self._estado_atual(),
        )
        self._history.add(chat_id, "user", text)
        try:
            reply = self._talker.reply(system, self._history.messages(chat_id))
        except TalkerError as exc:
            log.warning("Talker failed: %s", exc)
            self._history.drop_last(chat_id)
            return AssistantReply(FAILED_MESSAGE)

        self._history.add(chat_id, "assistant", reply.text)
        self._budget.add(reply.input_tokens, reply.output_tokens)
        return AssistantReply(
            reply.text,
            humor_offered=humor,
            warn_budget=self._budget.should_warn(),
        )
