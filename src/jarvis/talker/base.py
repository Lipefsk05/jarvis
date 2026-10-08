"""Provider-neutral interface for the Talker (the fast, real-time model)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class TalkerError(Exception):
    """The provider call failed. Message must never contain secrets."""


@dataclass(frozen=True)
class Reply:
    text: str
    input_tokens: int
    output_tokens: int


class Talker(Protocol):
    def reply(self, system: str, messages: list[dict[str, str]]) -> Reply:
        """Answer given a system prompt and [{'role': 'user'|'assistant', 'content': str}]."""
        ...
