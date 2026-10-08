"""Humor timing gate.

The code decides *when* a joke is allowed; the model only supplies the wit.
Rules (see persona/jarvis.md): no jokes on errors, urgency, money, irreversible
actions, sensitive topics or when the user sounds hurried/irritated, and a
minimum gap between jokes.
"""
from __future__ import annotations

import unicodedata


def _fold(text: str) -> str:
    """Lowercase and strip accents for keyword matching."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


SERIOUS_KEYWORDS = (
    "erro", "falha", "urgente", "urgencia", "prazo", "deadline",
    "dinheiro", "pix", "pagar", "pagamento", "fatura", "boleto",
    "apagar", "deletar", "excluir", "socorro", "deu ruim", "quebrou",
    "travou", "caiu", "preocupad", "triste", "hospital", "faleceu",
    "morreu", "demitid",
)
HURRY_KEYWORDS = ("pressa", "rapido", "rapidinho", "depressa", "correndo")


def is_serious(text: str) -> bool:
    """True when the message signals a context where humor must be off."""
    folded = _fold(text)
    if any(k in folded for k in SERIOUS_KEYWORDS):
        return True
    if any(k in folded for k in HURRY_KEYWORDS):
        return True
    letters = [c for c in text if c.isalpha()]
    # Mostly CAPS usually means irritation: treat as a hard stop.
    return len(letters) >= 8 and sum(c.isupper() for c in letters) / len(letters) > 0.6


class HumorGate:
    """Per-chat cooldown on top of the seriousness check."""

    def __init__(self, min_gap: int = 4, penalty_gap: int = 10) -> None:
        self.min_gap = min_gap
        self.penalty_gap = penalty_gap
        self._since: dict[int, int] = {}
        self._need: dict[int, int] = {}

    def decide(self, chat_id: int, text: str) -> bool:
        """Count one turn and say whether a joke is allowed in this reply."""
        need = self._need.get(chat_id, self.min_gap)
        since = self._since.get(chat_id, need)  # first turn may joke
        if is_serious(text):
            self._since[chat_id] = since + 1
            return False
        if since >= need:
            self._since[chat_id] = 0
            self._need[chat_id] = self.min_gap
            return True
        self._since[chat_id] = since + 1
        return False

    def feedback_not_funny(self, chat_id: int) -> None:
        """The user said the joke missed: restart the cooldown with a longer gap."""
        self._since[chat_id] = 0
        self._need[chat_id] = self.penalty_gap
