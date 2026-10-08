"""Short per-chat message window (in memory). Long-term memory lives in the vault."""
from __future__ import annotations


class History:
    def __init__(self, max_messages: int = 32) -> None:
        self._max = max_messages
        self._chats: dict[int, list[dict[str, str]]] = {}

    def add(self, chat_id: int, role: str, content: str) -> None:
        messages = self._chats.setdefault(chat_id, [])
        messages.append({"role": role, "content": content})
        if len(messages) > self._max:
            del messages[: len(messages) - self._max]
        # Providers require the conversation to start with a user message.
        while messages and messages[0]["role"] != "user":
            messages.pop(0)

    def messages(self, chat_id: int) -> list[dict[str, str]]:
        return [dict(m) for m in self._chats.get(chat_id, [])]

    def drop_last(self, chat_id: int) -> None:
        if self._chats.get(chat_id):
            self._chats[chat_id].pop()

    def clear(self, chat_id: int) -> None:
        self._chats.pop(chat_id, None)
