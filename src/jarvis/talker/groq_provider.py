"""Talker backed by the Groq API (OpenAI-compatible chat completions)."""
from __future__ import annotations

from .base import Reply, TalkerError

REQUEST_TIMEOUT_S = 15.0
# Auth/validation problems will not be fixed by trying another model.
NO_FALLBACK_CODES = {400, 401, 403}


class GroqTalker:
    def __init__(self, api_key: str, models: list[str], max_tokens: int = 400) -> None:
        from groq import Groq  # imported lazily so tests do not need the package

        # max_retries=0: fail fast and let our own model chain decide what to try next.
        self._client = Groq(api_key=api_key, timeout=REQUEST_TIMEOUT_S, max_retries=0)
        self._models = [m for m in models if m]
        self._max_tokens = max_tokens

    def _complete(self, model: str, system: str, messages: list[dict[str, str]]):
        return self._client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, *messages],
            max_tokens=self._max_tokens,
        )

    def reply(self, system: str, messages: list[dict[str, str]]) -> Reply:
        last_error = "NoModelConfigured"
        for model in self._models:
            try:
                response = self._complete(model, system, messages)
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
