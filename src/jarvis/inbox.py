"""Writes notes into the vault inbox. The assistant only ever writes here."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def write_note(inbox_dir: Path, text: str, now: datetime, source: str = "telegram") -> Path:
    """Create a timestamped Markdown note and return its path. Never overwrites."""
    inbox_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{now:%Y-%m-%d-%H%M%S}-nota"
    path = inbox_dir / f"{stem}.md"
    counter = 2
    while path.exists():
        path = inbox_dir / f"{stem}-{counter}.md"
        counter += 1
    body = (
        "---\n"
        f"origem: {source}\n"
        f"criado: {now:%Y-%m-%d %H:%M}\n"
        "---\n\n"
        f"{text.strip()}\n"
    )
    path.write_text(body, encoding="utf-8")
    return path


class NoteJournal:
    """Remembers the notes this assistant wrote, so it can take back the last one.

    It only ever deletes a file it wrote itself and that still sits directly inside the inbox,
    so an "undo" can never reach anything else in the vault.
    """

    KEEP = 20

    def __init__(self, path: Path) -> None:
        self._path = path

    def _read(self) -> list[str]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [item for item in data if isinstance(item, str)] if isinstance(data, list) else []

    def _write(self, names: list[str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(names[-self.KEEP:]), encoding="utf-8")

    def add(self, note: Path) -> None:
        self._write(self._read() + [note.name])

    def undo_last(self, inbox_dir: Path) -> tuple[str, str | None] | None:
        """Delete the most recent note written here. Returns (file name, its text), or None when there is nothing
        to undo. The text is None when the file is already gone (e.g. integrated into the Mind)."""
        names = self._read()
        if not names:
            return None
        name = names.pop()
        self._write(names)
        path = inbox_dir / name
        if path.parent != inbox_dir or not path.is_file():
            return name, None
        text = path.read_text(encoding="utf-8")
        path.unlink()
        return name, text.split("---\n", 2)[-1].strip()
