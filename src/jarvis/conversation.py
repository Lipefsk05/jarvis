"""Short per-chat message window, kept on disk so a restart does not wipe the conversation.
Long-term memory lives in the vault."""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class History:
    def __init__(self, max_messages: int = 32, path: Path | None = None) -> None:
        self._max = max_messages
        self._path = path
        self._chats: dict[int, list[dict[str, str]]] = {}
        # A reply runs in a worker thread while the reminder scheduler (event loop) also writes to the history.
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for chat_id, messages in raw.items():
                clean = [
                    {"role": m["role"], "content": m["content"]}
                    for m in messages
                    if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
                ]
                while clean and clean[0]["role"] != "user":
                    clean.pop(0)
                if clean:
                    self._chats[int(chat_id)] = clean[-self._max:]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            log.warning("Could not read the saved conversation at %s; starting empty", self._path)
            self._chats = {}

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # private: it is a personal conversation
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({str(k): v for k, v in self._chats.items()}, handle, ensure_ascii=False)
            os.replace(tmp, self._path)
        except OSError:
            log.warning("Could not save the conversation to %s", self._path)

    def add(self, chat_id: int, role: str, content: str) -> None:
        with self._lock:
            messages = self._chats.setdefault(chat_id, [])
            messages.append({"role": role, "content": content})
            if len(messages) > self._max:
                del messages[: len(messages) - self._max]
            # Providers require the conversation to start with a user message.
            while messages and messages[0]["role"] != "user":
                messages.pop(0)
            self._save()

    def messages(self, chat_id: int) -> list[dict[str, str]]:
        with self._lock:
            return [dict(m) for m in self._chats.get(chat_id, [])]

    def drop_last(self, chat_id: int) -> None:
        with self._lock:
            if self._chats.get(chat_id):
                self._chats[chat_id].pop()
                self._save()

    def clear(self, chat_id: int) -> None:
        with self._lock:
            self._chats.pop(chat_id, None)
            self._save()
