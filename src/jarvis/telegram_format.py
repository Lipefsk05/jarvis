"""Task lists formatted for reading in a Telegram chat (HTML parse mode, stdlib only).

The model-facing context in mind.py stays plain and compact; this is only for /tarefas.
"""
from __future__ import annotations

import html
import re
from collections import Counter

from .mind import GROUPS, Task

MAX_MESSAGE_CHARS = 3900  # Telegram caps a message at 4096
# Telegram turns "/word" anywhere in a message into a tappable command; a zero-width space
# after the slash keeps vault text such as "/privacidade" from looking like one.
_SLASH_WORD = re.compile(r"(?<![\w/])/(?=[A-Za-z])")


def safe(text: str) -> str:
    return _SLASH_WORD.sub("/​", html.escape(text, quote=False))


def _cap(text: str) -> str:
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    return text[:MAX_MESSAGE_CHARS].rsplit("\n", 1)[0] + "\n…"


def format_summary(tasks: list[Task]) -> str:
    if not tasks:
        return "Nenhuma pendência encontrada, senhor."
    counts = Counter((t.group, t.area) for t in tasks)
    lines = ["<b>Pendências por área</b>"]
    for group in GROUPS:
        areas = sorted((area, n) for (g, area), n in counts.items() if g == group)
        if areas:
            lines += ["", f"<b>{group.capitalize()}</b>"]
            lines += [f"• {safe(area)} — {n}" for area, n in areas]
    lines += ["", f"Total: {len(tasks)}. Use /tarefas &lt;área&gt; para ver os itens (ex.: /tarefas dindin)."]
    return _cap("\n".join(lines))


def format_items(items: list[Task], limit: int = 20) -> str:
    areas = {t.area for t in items}
    single_area = len(areas) == 1
    title = f"{len(items)} pendências" + (f" em {items[0].area}" if single_area else "")
    lines = [f"<b>{safe(title)}</b>"]
    group_key = None
    number = 0
    for task in items[:limit]:
        key = (task.area, task.section)
        if key != group_key:
            group_key = key
            label = task.section or "(sem seção)"
            if not single_area:
                label = f"{task.area} › {label}"
            total_in_section = sum(1 for t in items if (t.area, t.section) == key)
            lines += ["", f"<b>{safe(label)}</b> ({total_in_section})"]
        number += 1
        lines.append(f"{number}. {safe(task.title)}")
    if len(items) > limit:
        hint = f"/tarefas {items[0].area} palavra-da-seção" if single_area else "/tarefas área palavra-da-seção"
        lines += ["", f"Mostrando {limit} de {len(items)}. Refine com uma palavra da seção (ex.: {safe(hint)})."]
    return _cap("\n".join(lines))
