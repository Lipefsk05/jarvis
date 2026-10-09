"""Cleans reply habits the model keeps despite the prompt (stdlib only).

Seen live: markdown asterisks in a plain-text chat, "Entendo, senhor." as a reflex opener, a greeting
at the start of a reply to something that was not a greeting, the wrong part of the day for "e aí",
and an offer of help tacked onto a real answer. Asking the model to stop did not hold, so the code
fixes the text instead. Every cleanup keeps the reply when removing would leave nothing.
"""
from __future__ import annotations

import re
from datetime import datetime

from .textutil import fold

_PERIOD = re.compile(r"^\s*(bom dia|boa tarde|boa noite)\b", re.IGNORECASE)
_GREETING_OPENER = re.compile(r"^\s*(?:bom dia|boa tarde|boa noite|olá|ola|oi)\s*[,.!]*\s*(?:senhor\s*[,.!]*\s*)?", re.IGNORECASE)
_REFLEX_OPENER = re.compile(r"^\s*(?:entendo|compreendido|entendido)\s*[,.!]+\s*(?:senhor\s*[,.!]*\s*)?", re.IGNORECASE)
_OFFER = re.compile(
    r"em que (?:posso|poderia)|no que (?:posso|poderia)|posso (?:te |lhe )?(?:ajudar|auxiliar)|como posso (?:atender|ajudar|ser)"
    r"|mais alguma (?:coisa|d[uú]vida)|precisa de (?:mais )?algo",
    re.IGNORECASE,
)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


def period_greeting(now: datetime) -> str:
    if 5 <= now.hour < 12:
        return "Bom dia"
    if 12 <= now.hour < 18:
        return "Boa tarde"
    return "Boa noite"


def strip_markdown(text: str) -> str:
    """Plain text for Telegram: drop bold/italic marks, backticks, headings and bullet dashes (numbered lines stay)."""
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), text, flags=re.DOTALL)
    text = re.sub(r"`+([^`]*)`+", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^(\s*)[-*•]\s+", r"\1", text)
    return text.strip()


def _keep(original: str, candidate: str) -> str:
    candidate = candidate.strip()
    return candidate if candidate else original


def _drop_offer(text: str) -> str:
    """Remove a closing offer of help ("Posso ajudar em mais alguma coisa?") when something else remains."""
    sentences = _SENTENCE_BREAK.split(text.strip())
    if len(sentences) > 1 and _OFFER.search(sentences[-1]):
        return _keep(text, " ".join(sentences[:-1]))
    return text


def polish(user_text: str, reply: str, now: datetime, *, is_greeting: bool, greeting_request: bool, allows_help: bool) -> str:
    """Fix the reply's habits. `is_greeting` / `greeting_request` describe what the user wrote
    (just a greeting, or a greeting followed by a request); `allows_help` is whether this turn's style
    hint welcomed an offer of help."""
    text = strip_markdown(reply)
    text = _keep(text, _REFLEX_OPENER.sub("", text))
    if not (is_greeting or greeting_request):
        text = _keep(text, _GREETING_OPENER.sub("", text))  # nobody greeted: do not open with a greeting
        return _drop_offer(text)
    users_period = _PERIOD.match(fold(user_text))
    if not users_period:  # "oi", "e aí": the part of the day comes from the clock, not from the model's guess
        text = _PERIOD.sub(lambda m: period_greeting(now), text, count=1)
    if not allows_help:
        text = _drop_offer(text)
    return text
