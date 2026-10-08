"""Builds the configured Talker. The provider is swappable by configuration only."""
from __future__ import annotations

from ..config import Settings
from .base import Talker


def build_talker(settings: Settings) -> Talker:
    if settings.provider == "anthropic":
        from .anthropic_provider import AnthropicTalker

        return AnthropicTalker(settings.anthropic_api_key, settings.model)
    if settings.provider == "gemini":
        from .gemini_provider import GeminiTalker

        return GeminiTalker(settings.gemini_api_key, [settings.model, *settings.fallback_models])
    raise ValueError(f"unknown provider: {settings.provider}")
