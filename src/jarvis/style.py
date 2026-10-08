"""Per-turn style hints that force variety on the replies a model tends to canonise.

Observed live: every greeting got the same "<greeting>, senhor. Em que posso ser útil?",
even without any example in the prompt, and asking the model to "vary" did nothing. So
variety is enforced here: for greetings and thanks a hint is drawn that differs from the
last one used in that chat, and the model only writes the wording.
"""
from __future__ import annotations

import random
import re

from .textutil import fold

_GREETING = re.compile(
    r"^(?:oi+|ola+|opa|eai|e ai|ei|hey|hello|salve|fala|alo|bom d\w*|boa (?:tarde|noite|t\w*|n\w*)|boas|bao)\b"
)
_THANKS = re.compile(r"^(?:valeu|vlw|obrigad\w*|brigad\w*|brigadao|agradeco|grato|thanks|tks|thx)\b")

GREETING_HINTS = (
    "Cumprimente e pergunte, com suas próprias palavras, o que o senhor tem em mente hoje.",
    "Cumprimente e diga que está às ordens, sem fazer pergunta.",
    "Cumprimente e pergunte, de forma breve, como vai o dia do senhor.",
    "Cumprimente e faça uma observação elegante sobre o horário ou o dia da semana, depois coloque-se à disposição.",
    "Cumprimente apenas, com uma frase curta de prontidão.",
    "Cumprimente e pergunte se há algo por onde o senhor queira começar.",
    "Cumprimente e pergunte, com um toque de ironia seca, o que o senhor tem planejado para hoje.",
)
THANKS_HINTS = (
    "Responda ao agradecimento com uma frase curta e formal.",
    "Responda ao agradecimento com uma única palavra ou expressão curta e polida.",
    "Responda ao agradecimento dizendo que foi um prazer, de forma contida.",
)
# Offering help is welcome now and then; these hints allow it, the others steer away from it.
HELP_HINTS = (
    "Cumprimente e ofereça ajuda de forma natural e breve, perguntando em que pode ajudar o senhor hoje.",
    "Cumprimente e pergunte se o senhor precisa de alguma coisa, de forma natural e breve.",
)
GREETING_POOL = GREETING_HINTS + HELP_HINTS
STIFF_RULE = (
    "Use uma frase natural, curta e direta, no tom do J.A.R.V.I.S. dos filmes: nada de construções "
    'rebuscadas ou arcaicas (como "servir-lhe", "ocupar-me", "dispor-se").'
)
AVOID_RULE = 'Evite a fórmula "em que posso ser útil" e variações como "posso ajudar".'


def _compose(hint: str) -> str:
    return f"{hint} {STIFF_RULE}" + ("" if hint in HELP_HINTS else f" {AVOID_RULE}")


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", fold(text))


def is_greeting(text: str) -> bool:
    words = _words(text)
    return 0 < len(words) <= 4 and bool(_GREETING.match(" ".join(words)))


def is_thanks(text: str) -> bool:
    words = _words(text)
    return 0 < len(words) <= 4 and bool(_THANKS.match(" ".join(words)))


class StyleHints:
    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self._last: dict[tuple[int, str], str] = {}

    def _pick(self, chat_id: int, kind: str, options: tuple[str, ...]) -> str:
        last = self._last.get((chat_id, kind))
        choices = [o for o in options if o != last] or list(options)
        pick = self._rng.choice(choices)
        self._last[(chat_id, kind)] = pick
        return pick

    def hint_for(self, chat_id: int, text: str) -> str:
        """A style hint for greetings and thanks, or '' for everything else."""
        if is_greeting(text):
            return _compose(self._pick(chat_id, "greeting", GREETING_POOL))
        if is_thanks(text):
            return _compose(self._pick(chat_id, "thanks", THANKS_HINTS))
        return ""
