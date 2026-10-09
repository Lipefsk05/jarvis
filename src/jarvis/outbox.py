"""Proactive messages (reminders, later digests) leave through here. The outbox picks a channel
and reports whether the message really went out, so callers only mark things as delivered
after a real delivery. Telegram is the only channel today; voice plugs in as another Channel."""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Protocol

log = logging.getLogger(__name__)


class Channel(Protocol):
    name: str

    async def send(self, text: str) -> None:
        """Deliver the text or raise. Returning means it went out."""


class Outbox:
    def __init__(self, channels: list[Channel], route: Callable[[], str] | None = None) -> None:
        if not channels:
            raise ValueError("an outbox needs at least one channel")
        self._channels = {c.name: c for c in channels}
        self._default = channels[0].name
        self._route = route or (lambda: self._default)

    async def deliver(self, text: str) -> bool:
        """Send through the preferred channel, falling back to the others. True if any delivered."""
        preferred = self._route()
        order = [preferred] + [n for n in self._channels if n != preferred]
        for name in order:
            channel = self._channels.get(name)
            if channel is None:
                continue
            try:
                await channel.send(text)
                return True
            except Exception as exc:  # a channel being down must never crash the scheduler
                log.warning("Channel %s failed to deliver: %s", name, type(exc).__name__)
        return False


class TelegramChannel:
    name = "telegram"

    def __init__(self, bot, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id

    async def send(self, text: str) -> None:
        from telegram import LinkPreviewOptions

        await self._bot.send_message(
            chat_id=self._chat_id, text=text[:4096], link_preview_options=LinkPreviewOptions(is_disabled=True)
        )
