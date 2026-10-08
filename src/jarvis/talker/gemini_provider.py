"""Talker backed by the Gemini API. Free tier is for testing only: Google may use the prompts."""
from __future__ import annotations

from .base import Reply, TalkerError


class GeminiTalker:
    def __init__(self, api_key: str, model: str, max_tokens: int = 400) -> None:
        from google import genai  # imported lazily so tests do not need the package
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def reply(self, system: str, messages: list[dict[str, str]]) -> Reply:
        types = self._types
        contents = [
            types.Content(
                role="user" if m["role"] == "user" else "model",
                parts=[types.Part(text=m["content"])],
            )
            for m in messages
        ]
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system, max_output_tokens=self._max_tokens
                ),
            )
        except Exception as exc:
            raise TalkerError(type(exc).__name__) from exc
        text = (response.text or "").strip()
        if not text:
            raise TalkerError("EmptyResponse")
        usage = response.usage_metadata
        return Reply(
            text,
            getattr(usage, "prompt_token_count", 0) or 0,
            getattr(usage, "candidates_token_count", 0) or 0,
        )
