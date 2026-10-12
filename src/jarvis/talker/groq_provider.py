"""Talker backed by the Groq API (OpenAI-compatible chat completions)."""
from __future__ import annotations

import json
from datetime import datetime

from .base import Reply, TalkerError, ToolCall

REQUEST_TIMEOUT_S = 15.0
# Auth/validation problems will not be fixed by trying another model.
NO_FALLBACK_CODES = {400, 401, 403}


def parse_limits(headers) -> dict | None:
    """Rate limits the API reports on every response (requests per day, tokens per minute)."""
    def number(name: str) -> int | None:
        try:
            return int(headers.get(name))
        except (TypeError, ValueError):
            return None

    limits = {
        "requests_limit": number("x-ratelimit-limit-requests"),
        "requests_remaining": number("x-ratelimit-remaining-requests"),
        "tokens_limit": number("x-ratelimit-limit-tokens"),
        "tokens_remaining": number("x-ratelimit-remaining-tokens"),
    }
    return limits if any(v is not None for v in limits.values()) else None


# The thinking tokens count against max_tokens, so a deeper level needs a bigger allowance.
MAX_TOKENS_BY_REASONING = {"low": 700, "medium": 1500, "high": 3000}


class GroqTalker:
    def __init__(self, api_key: str, models: list[str], max_tokens: int | None = None, reasoning: str = "low",
                 timeout_s: float = REQUEST_TIMEOUT_S) -> None:
        from groq import Groq  # imported lazily so tests do not need the package

        # max_retries=0: fail fast and let our own model chain decide what to try next.
        self._client = Groq(api_key=api_key, timeout=timeout_s, max_retries=0)
        self._models = [m for m in models if m]
        self._reasoning = reasoning
        self._max_tokens = max_tokens or MAX_TOKENS_BY_REASONING.get(reasoning, 700)
        self.limits: dict | None = None  # last limits reported by the API, for /uso

    def _extra(self, model: str) -> dict:
        # gpt-oss models reason before answering and those tokens count against max_tokens and against the
        # per-minute token limit; "low" keeps a conversational assistant fast.
        return {"reasoning_effort": self._reasoning} if model.startswith("openai/gpt-oss") else {}

    def _complete(self, model: str, system: str, messages: list[dict[str, str]], tools: list[dict] | None = None):
        extra = self._extra(model)
        if tools:
            extra["tools"] = tools
            extra["tool_choice"] = "auto"
        raw = self._client.chat.completions.with_raw_response.create(
            model=model,
            messages=[{"role": "system", "content": system}, *messages],
            max_tokens=self._max_tokens,
            **extra,
        )
        limits = parse_limits(raw.headers)
        if limits:
            self.limits = {**limits, "at": datetime.now().strftime("%H:%M")}
        return raw.parse()

    def reply(self, system: str, messages: list[dict[str, str]], tools: list[dict] | None = None) -> Reply:
        last_error, last_code = "NoModelConfigured", None
        for model in self._models:
            try:
                response = self._complete(model, system, messages, tools)
            except Exception as exc:  # SDK errors never carry the key; keep only type and code
                code = getattr(exc, "status_code", None)
                last_error, last_code = f"{type(exc).__name__}:{code}", code
                if code in NO_FALLBACK_CODES:
                    break
                continue
            choices = getattr(response, "choices", None) or []
            if not choices:
                last_error, last_code = "EmptyResponse", None
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
                last_error, last_code = "MaxTokens", None
                continue
            text = (choices[0].message.content or "").strip()
            if not text:
                last_error, last_code = "EmptyResponse", None
                continue
            usage = response.usage
            return Reply(
                text,
                getattr(usage, "prompt_tokens", 0) or 0,
                getattr(usage, "completion_tokens", 0) or 0,
            )
        raise TalkerError(last_error, last_code)
