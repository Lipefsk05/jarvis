"""Provider-neutral interface for the Talker (the fast, real-time model)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class TalkerError(Exception):
    """The provider call failed. Message must never contain secrets."""


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict


@dataclass(frozen=True)
class Reply:
    text: str
    input_tokens: int
    output_tokens: int
    provider: str = ""  # filled by the chain
    cost_usd: float | None = None  # filled by the chain, using that provider's prices
    tool_call: ToolCall | None = None  # set when the model chose to call a tool instead of answering


class Talker(Protocol):
    def reply(self, system: str, messages: list[dict[str, str]], tools: list[dict] | None = None) -> Reply:
        """Answer given a system prompt and [{'role': 'user'|'assistant', 'content': str}].

        `tools` are OpenAI-style function specs; providers that do not support them ignore them."""
        ...
