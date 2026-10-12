"""Tries several providers in order. Each member keeps its own prices, so cost stays honest."""
from __future__ import annotations

import dataclasses
import logging
import time
from dataclasses import dataclass
from typing import Callable

from .base import Reply, Talker, TalkerError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChainMember:
    name: str
    talker: Talker
    price_in: float  # USD per million input tokens
    price_out: float  # USD per million output tokens
    private_ok: bool = True  # False: may use what it receives (free Gemini), so never sees private context


# Failures of the answer itself (cut, empty) say nothing about the provider being down.
CONTENT_FAILURES = {"MaxTokens", "EmptyResponse", "NoModelConfigured"}
RATE_LIMIT_COOLDOWN_S = 60.0  # the limits are per minute
AUTH_COOLDOWN_S = 600.0  # a bad key will not fix itself in a minute
DOWN_COOLDOWN_S = 120.0  # timeout, connection or server error


def cooldown_for(exc: TalkerError) -> float:
    """How long to leave a provider alone after this failure; 0 = keep trying it next time."""
    if str(exc) in CONTENT_FAILURES:
        return 0.0
    code = exc.code
    if code == 429:
        return RATE_LIMIT_COOLDOWN_S
    if code in (401, 403):
        return AUTH_COOLDOWN_S
    if code is not None and code < 500:  # 400 and friends: our request, not the provider
        return 0.0
    return DOWN_COOLDOWN_S


class ChainTalker:
    """Circuit breaker: a provider that just failed is skipped for a while, so the next messages
    do not each wait for its timeout. If every provider is cooling down, all are tried anyway."""

    def __init__(self, members: list[ChainMember], clock: Callable[[], float] = time.monotonic) -> None:
        self._members = list(members)
        self._clock = clock
        self._skip_until: dict[str, float] = {}

    @property
    def names(self) -> list[str]:
        return [m.name for m in self._members]

    def info(self) -> list[dict]:
        """For /uso: each provider, its main model, whether it is free, and the last limits it reported."""
        out = []
        for member in self._members:
            models = list(getattr(member.talker, "_models", []))
            if not models and hasattr(member.talker, "_model"):
                models = [member.talker._model]
            out.append({
                "name": member.name,
                "model": models[0] if models else "",
                "free": member.price_in == 0 and member.price_out == 0,
                "limits": getattr(member.talker, "limits", None),
            })
        return out

    def reply(self, system: str, messages: list[dict[str, str]], tools: list[dict] | None = None,
              private: bool = False) -> Reply:
        """`private`: the prompt carries the user's own data (tasks); only providers that keep it to themselves answer."""
        errors: list[str] = []
        now = self._clock()
        members = [m for m in self._members if m.private_ok] if private else self._members
        ready = [m for m in members if self._skip_until.get(m.name, 0.0) <= now]
        for member in ready or members:
            try:
                reply = member.talker.reply(system, messages, tools)
            except TalkerError as exc:  # also on bad keys: another provider may still work
                errors.append(f"{member.name}:{exc}")
                cooldown = cooldown_for(exc)
                if cooldown:
                    self._skip_until[member.name] = self._clock() + cooldown
                log.warning("Provider %s failed: %s%s", member.name, exc, f" (skipped for {cooldown:.0f}s)" if cooldown else "")
                continue
            self._skip_until.pop(member.name, None)
            if member is not self._members[0]:
                log.info("Answered by fallback provider %s", member.name)
            cost = reply.input_tokens * member.price_in / 1e6 + reply.output_tokens * member.price_out / 1e6
            return dataclasses.replace(reply, provider=member.name, cost_usd=cost)
        raise TalkerError(" | ".join(errors) or "NoProvider")
