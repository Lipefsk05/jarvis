"""How words are *said*: a table of written word -> respelling, applied only to the text that goes to the voice.
The screen and Telegram keep the real spelling ("Dindin"); the voice gets "Dindim". Stdlib only, so the voice
prototype (Windows, no install) can import it too."""
from __future__ import annotations

import json
import re
from pathlib import Path


def load(path: Path) -> dict[str, str]:
    """The table from `persona/pronuncias.json`; a missing or broken file means no changes."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def for_speech(text: str, table: dict[str, str]) -> str:
    """`text` with every whole word of the table replaced (any capitalisation). Longest entries win, so
    "Next.js" is tried before "Next"."""
    if not table:
        return text
    lowered = {k.lower(): v for k, v in table.items()}
    keys = sorted(lowered, key=len, reverse=True)
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(k) for k in keys) + r")(?!\w)", re.IGNORECASE)
    return pattern.sub(lambda m: lowered[m.group(0).lower()], text)
