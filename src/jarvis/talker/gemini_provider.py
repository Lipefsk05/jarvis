"""Talker backed by the Gemini API. Free tier is for testing only: Google may use the prompts."""
from __future__ import annotations

from .base import Reply, TalkerError

REQUEST_TIMEOUT_MS = 15000
# Auth/validation problems will not be fixed by trying another model.
NO_FALLBACK_CODES = {400, 401, 403}


class GeminiTalker:
    def __init__(self, api_key: str, models: list[str], max_tokens: int = 400) -> None:
        from google import genai  # imported lazily so tests do not need the package
        from google.genai import types

        self._types = types
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS)
        )
        self._models = [m for m in models if m]
        self._max_tokens = max_tokens

    def _config(self, model: str, system: str):
        kwargs = {"system_instruction": system, "max_output_tokens": self._max_tokens}
        # These models think by default and thinking tokens count against
        # max_output_tokens, which truncates or empties short answers (seen live).
        # A conversational assistant does not need them.
        if model.startswith("gemini-2.5"):
            kwargs["thinking_config"] = self._types.ThinkingConfig(thinking_budget=0)
        elif model.startswith("gemini-3"):
            kwargs["thinking_config"] = self._types.ThinkingConfig(
                thinking_level=self._types.ThinkingLevel.MINIMAL
            )
        return self._types.GenerateContentConfig(**kwargs)

    def _generate(self, model: str, system: str, contents: list):
        return self._client.models.generate_content(
            model=model, contents=contents, config=self._config(model, system)
        )

    def reply(self, system: str, messages: list[dict[str, str]]) -> Reply:
        types = self._types
        contents = [
            types.Content(
                role="user" if m["role"] == "user" else "model",
                parts=[types.Part(text=m["content"])],
            )
            for m in messages
        ]
        last_error = "NoModelConfigured"
        for model in self._models:
            try:
                response = self._generate(model, system, contents)
            except Exception as exc:  # SDK errors never carry the key; keep only type and code
                code = getattr(exc, "code", None)
                last_error = f"{type(exc).__name__}:{code}"
                if code in NO_FALLBACK_CODES:
                    break
                continue
            candidates = getattr(response, "candidates", None) or []
            finish = str(getattr(candidates[0], "finish_reason", "")) if candidates else ""
            if "MAX_TOKENS" in finish:  # a sentence cut in half is worse than trying another model
                last_error = "MaxTokens"
                continue
            text = (response.text or "").strip()
            if not text:
                last_error = "EmptyResponse"
                continue
            usage = response.usage_metadata
            # Thinking tokens are billed as output.
            output = (getattr(usage, "candidates_token_count", 0) or 0) + (
                getattr(usage, "thoughts_token_count", 0) or 0
            )
            return Reply(text, getattr(usage, "prompt_token_count", 0) or 0, output)
        raise TalkerError(last_error)
