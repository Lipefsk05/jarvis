"""Builds the configured Talker chain. Providers are swappable by configuration only."""
from __future__ import annotations

import logging

from ..config import DEFAULT_FALLBACKS, DEFAULT_MODELS, DEFAULT_PRICES, Settings
from .base import Talker
from .chain import ChainMember, ChainTalker

log = logging.getLogger(__name__)


def _build_one(provider: str, api_key: str, models: list[str], reasoning: str = "low", timeout_s: float = 15.0) -> Talker:
    if provider == "anthropic":
        from .anthropic_provider import AnthropicTalker

        return AnthropicTalker(api_key, models[0], timeout_s=timeout_s)
    if provider == "gemini":
        from .gemini_provider import GeminiTalker

        return GeminiTalker(api_key, models, timeout_s=timeout_s)
    if provider == "groq":
        from .groq_provider import GroqTalker

        return GroqTalker(api_key, models, reasoning=reasoning, timeout_s=timeout_s)
    raise ValueError(f"unknown provider: {provider}")


def build_talker(settings: Settings) -> ChainTalker:
    """Primary provider first (honouring the configured model, fallback models and
    price overrides), then each fallback provider with its own defaults. Fallback
    providers without an API key are skipped with a warning."""
    members = [
        ChainMember(
            settings.provider,
            _build_one(settings.provider, settings.key_for(settings.provider),
                       [settings.model, *settings.fallback_models], settings.groq_reasoning, settings.talker_timeout_s),
            settings.price_in,
            settings.price_out,
        )
    ]
    for provider in settings.fallback_providers:
        key = settings.key_for(provider)
        if not key:
            log.warning("Fallback provider %s skipped: no API key configured", provider)
            continue
        price_in, price_out = DEFAULT_PRICES.get(provider, (0.0, 0.0))
        members.append(
            ChainMember(
                provider,
                _build_one(provider, key, [DEFAULT_MODELS[provider], *DEFAULT_FALLBACKS[provider]], settings.groq_reasoning,
                           settings.talker_timeout_s),
                price_in,
                price_out,
            )
        )
    return ChainTalker(members)
