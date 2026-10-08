"""Small text helpers (stdlib only)."""
from __future__ import annotations

import unicodedata


def fold(text: str) -> str:
    """Lowercase and strip accents, for keyword matching."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
