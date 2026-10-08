"""Parsing of messages that are handled by code instead of the model."""
from __future__ import annotations

import re

_NOTE = re.compile(r"^\s*(?:anota|anote|anotar)\b[\s:,\-]*(.*)$", re.IGNORECASE | re.DOTALL)


def parse_note_request(text: str) -> str | None:
    """Return the text to save if the message is a note request, else None.

    "anota comprar café" -> "comprar café"; a bare "anota" -> "" (ask what to note);
    "anotaram tudo" or any other sentence -> None (goes to the model).
    """
    match = _NOTE.match(text)
    if not match:
        return None
    return match.group(1).strip()
