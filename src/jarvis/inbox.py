"""Writes notes into the vault inbox. The assistant only ever writes here."""
from __future__ import annotations

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
