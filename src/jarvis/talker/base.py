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


NO_TOOLS_NOTICE = (
    "\n\n## Neste momento\n\n"
    "As ferramentas (anotar, lembretes, tarefas, gasto) estão **indisponíveis agora**: você só consegue conversar. "
    "Se o senhor pedir algo que exigiria uma delas, diga com franqueza que não consegue executar isso agora e indique "
    "o comando equivalente: /anota para notas, /lembra para marcar lembretes, /lembretes para listar, /cancela para "
    "cancelar, /tarefas para tarefas, /uso para o gasto. **Nunca** diga que chamou, executou ou salvou algo."
)


def without_tools(system: str, tools: list[dict] | None) -> str:
    """For providers that cannot run tools: tell the model so, or it imitates calling them."""
    return system + NO_TOOLS_NOTICE if tools else system
