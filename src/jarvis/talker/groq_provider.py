"""Talker backed by the Groq API (OpenAI-compatible chat completions)."""
from __future__ import annotations

import json

from .base import Reply, TalkerError, ToolCall

REQUEST_TIMEOUT_S = 15.0
# Auth/validation problems will not be fixed by trying another model.
NO_FALLBACK_CODES = {400, 401, 403}


class GroqTalker:
    def __init__(self, api_key: str, models: list[str], max_tokens: int = 700) -> None:
        from groq import Groq  # imported lazily so tests do not need the package

        # max_retries=0: fail fast and let our own model chain decide what to try next.
        self._client = Groq(api_key=api_key, timeout=REQUEST_TIMEOUT_S, max_retries=0)
        self._models = [m for m in models if m]
        self._max_tokens = max_tokens

    @staticmethod
    def _extra(model: str) -> dict:
        # gpt-oss models reason before answering and those tokens count against
        # max_tokens; keep it minimal for a conversational assistant.
        return {"reasoning_effort": "low"} if model.startswith("openai/gpt-oss") else {}

    def _complete(self, model: str, system: str, messages: list[dict[str, str]], tools: list[dict] | None = None):
        extra = self._extra(model)
        if tools:
            extra["tools"] = tools
            extra["tool_choice"] = "auto"
        return self._client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, *messages],
            max_tokens=self._max_tokens,
            **extra,
        )

    def reply(self, system: str, messages: list[dict[str, str]], tools: list[dict] | None = None) -> Reply:
        last_error = "NoModelConfigured"
        for model in self._models:
            try:
                response = self._complete(model, system, messages, tools)
            except Exception as exc:  # SDK errors never carry the key; keep only type and code
                code = getattr(exc, "status_code", None)
                last_error = f"{type(exc).__name__}:{code}"
                if code in NO_FALLBACK_CODES:
                    break
                continue
            choices = getattr(response, "choices", None) or []
            if not choices:
                last_error = "EmptyResponse"
                continue
            calls = getattr(choices[0].message, "tool_calls", None) or []
            if calls:
                function = calls[0].function
                try:
                    arguments = json.loads(function.arguments or "{}")
                except ValueError:
                    arguments = {}
                usage = response.usage
                return Reply(
                    (choices[0].message.content or "").strip(),
                    getattr(usage, "prompt_tokens", 0) or 0,
                    getattr(usage, "completion_tokens", 0) or 0,
                    tool_call=ToolCall(function.name, arguments if isinstance(arguments, dict) else {}),
                )
            if getattr(choices[0], "finish_reason", None) == "length":  # cut mid-sentence
                last_error = "MaxTokens"
                continue
            text = (choices[0].message.content or "").strip()
            if not text:
                last_error = "EmptyResponse"
                continue
            usage = response.usage
            return Reply(
                text,
                getattr(usage, "prompt_tokens", 0) or 0,
                getattr(usage, "completion_tokens", 0) or 0,
            )
        raise TalkerError(last_error)
