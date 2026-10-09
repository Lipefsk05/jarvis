"""Talker backed by the Anthropic Messages API."""
from __future__ import annotations

from .base import Reply, TalkerError, without_tools


class AnthropicTalker:
    def __init__(self, api_key: str, model: str, max_tokens: int = 400) -> None:
        import anthropic  # imported lazily so tests do not need the package

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def reply(self, system: str, messages: list[dict[str, str]], tools: list[dict] | None = None) -> Reply:
        # Tools are not wired for this provider yet: it answers in plain text, and is told so.
        system = without_tools(system, tools)
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=messages,
            )
        except Exception as exc:  # SDK errors never carry the key; keep only the type
            raise TalkerError(type(exc).__name__) from exc
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        if not text:
            raise TalkerError("EmptyResponse")
        return Reply(text, response.usage.input_tokens, response.usage.output_tokens)
