"""Reminder storage: one JSON file, written atomically. It only stores and queries; deciding
when and where to deliver is the scheduler's job."""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

PENDING, SENT, LATE, LOST, CANCELLED = "pendente", "enviado", "atrasado", "perdido", "cancelado"
CLOSING = (SENT, LATE, LOST)
MAX_TEXT_CHARS = 500
MAX_PENDING = 200
KEEP_CLOSED_DAYS = 30


class ReminderError(ValueError):
    """The reminder cannot be stored (empty text, too many pending, ...). The message is user-safe."""


@dataclass
class Reminder:
    id: int
    text: str
    due: datetime
    status: str
    created: datetime
    closed: datetime | None = None
    event: datetime | None = None  # when the thing happens, if `due` is an advance warning before it

    def to_json(self) -> dict:
        return {
            "id": self.id, "text": self.text, "due": self.due.isoformat(), "status": self.status,
            "created": self.created.isoformat(), "closed": self.closed.isoformat() if self.closed else None,
            "event": self.event.isoformat() if self.event else None,
        }

    @staticmethod
    def from_json(raw: dict) -> "Reminder":
        closed, event = raw.get("closed"), raw.get("event")
        return Reminder(
            id=int(raw["id"]), text=str(raw["text"]), due=datetime.fromisoformat(raw["due"]),
            status=str(raw["status"]), created=datetime.fromisoformat(raw["created"]),
            closed=datetime.fromisoformat(closed) if closed else None,
            event=datetime.fromisoformat(event) if event else None,
        )


def clean_text(text: str) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    return re.sub(r" {2,}", " ", text).strip()[:MAX_TEXT_CHARS]


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")


class ReminderStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._next_id = 1
        self._items: dict[int, Reminder] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            items = [Reminder.from_json(item) for item in raw["items"]]
            self._items = {item.id: item for item in items}
            self._next_id = max(int(raw["next_id"]), max(self._items, default=0) + 1)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            quarantine = self._path.with_suffix(".corrupt")
            log.warning("Could not read reminders at %s; moved to %s and starting empty", self._path, quarantine)
            try:
                os.replace(self._path, quarantine)  # never overwrite what the user may still want to recover
            except OSError:
                pass
            self._items, self._next_id = {}, 1

    def _save(self, now: datetime) -> None:
        cutoff = now - timedelta(days=KEEP_CLOSED_DAYS)
        self._items = {
            i: r for i, r in self._items.items() if r.status == PENDING or (r.closed or r.created) >= cutoff
        }
        payload = {"next_id": self._next_id, "items": [r.to_json() for r in self._items.values()]}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            os.replace(tmp, self._path)
        except OSError:
            log.warning("Could not save reminders to %s", self._path)

    def add(self, text: str, due: datetime, now: datetime, event: datetime | None = None) -> Reminder:
        """Store a reminder. Asking for the same text at the same time again returns the existing one.
        `event` is set when `due` is an advance warning ("10 minutes before")."""
        _aware(due, "due"), _aware(now, "now")
        if event is not None:
            _aware(event, "event")
        text = clean_text(text)
        if not text:
            raise ReminderError("O que devo lembrar, senhor?")
        if due <= now:
            raise ReminderError("Esse horário já passou, senhor.")
        for item in self.pending():
            if item.text == text and item.due == due:
                return item
        if len(self.pending()) >= MAX_PENDING:
            raise ReminderError("Há lembretes demais pendentes, senhor. Cancele alguns antes de criar outro.")
        reminder = Reminder(self._next_id, text, due, PENDING, now, event=event)
        self._next_id += 1
        self._items[reminder.id] = reminder
        self._save(now)
        return reminder

    def get(self, reminder_id: int) -> Reminder | None:
        return self._items.get(reminder_id)

    def pending(self) -> list[Reminder]:
        return sorted((r for r in self._items.values() if r.status == PENDING), key=lambda r: (r.due, r.id))

    def due(self, now: datetime) -> list[Reminder]:
        _aware(now, "now")
        return [r for r in self.pending() if r.due <= now]

    def cancel(self, reminder_id: int, now: datetime) -> Reminder | None:
        """Cancel a pending reminder; None if it does not exist or is already closed."""
        item = self._items.get(reminder_id)
        if item is None or item.status != PENDING:
            return None
        item.status, item.closed = CANCELLED, now
        self._save(now)
        return item

    def close(self, reminder_id: int, status: str, now: datetime) -> Reminder | None:
        """Mark a pending reminder as sent, sent late, or lost. None if it is not pending."""
        if status not in CLOSING:
            raise ValueError(f"cannot close a reminder as {status!r}")
        item = self._items.get(reminder_id)
        if item is None or item.status != PENDING:
            return None
        item.status, item.closed = status, now
        self._save(now)
        return item

    def closed_since(self, since: datetime, status: str | None = None) -> list[Reminder]:
        """Closed reminders (optionally of one status) closed at or after `since`, oldest first."""
        found = [r for r in self._items.values() if r.status != PENDING and r.closed and r.closed >= since]
        if status:
            found = [r for r in found if r.status == status]
        return sorted(found, key=lambda r: (r.closed, r.id))
