"""Tries several providers in order. Each member keeps its own prices, so cost stays honest."""
from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass

from .base import Reply, Talker, TalkerError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChainMember:
    name: str
    talker: Talker
    price_in: float  # USD per million input tokens
    price_out: float  # USD per million output tokens


class ChainTalker:
    def __init__(self, members: list[ChainMember]) -> None:
        self._members = list(members)

    @property
    def names(self) -> list[str]:
        return [m.name for m in self._members]

    def reply(self, system: str, messages: list[dict[str, str]], tools: list[dict] | None = None) -> Reply:
        errors: list[str] = []
        for index, member in enumerate(self._members):
            try:
                reply = member.talker.reply(system, messages, tools)
            except TalkerError as exc:  # also on bad keys: another provider may still work
                errors.append(f"{member.name}:{exc}")
                log.warning("Provider %s failed: %s", member.name, exc)
                continue
            if index > 0:
                log.info("Answered by fallback provider %s", member.name)
            cost = reply.input_tokens * member.price_in / 1e6 + reply.output_tokens * member.price_out / 1e6
            return dataclasses.replace(reply, provider=member.name, cost_usd=cost)
        raise TalkerError(" | ".join(errors) or "NoProvider")
