"""Read-only view of the pending tasks in the Mind vault (stdlib only).

Nothing here writes to the vault. Tasks are the `- [ ]` bullets under tarefas/pessoal
and tarefas/empresa; the bullets are long, so only a short title is exposed.
"""
from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from dataclasses import dataclass
from pathlib import Path

from .textutil import fold

_TASK = re.compile(r"^- \[ \]\s+(.*)$")
_HEADING = re.compile(r"^##\s+(.*)$")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
GROUPS = ("pessoal", "empresa")
INDEX_FILES = {"pessoal", "empresa"}  # folder indexes carry no tasks


@dataclass(frozen=True)
class Task:
    group: str    # "pessoal" or "empresa"
    area: str     # file stem, e.g. "carreira"
    section: str  # the ## heading it sits under
    title: str


def short_title(text: str, max_chars: int = 110) -> str:
    text = _LINK.sub(r"\1", text)
    lead = re.match(r"\s*\*\*(.+?)\*\*", text)
    title = lead.group(1) if lead else text
    title = _BOLD.sub(r"\1", title).replace("`", "")
    title = re.sub(r"\s+", " ", title).strip(" -:;,.")
    if len(title) > max_chars:
        title = title[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
    return title


def load_pending(mind_dir: Path) -> list[Task]:
    tasks: list[Task] = []
    for group in GROUPS:
        folder = mind_dir / "tarefas" / group
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            if path.stem in INDEX_FILES:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            section = ""
            for line in lines:
                heading = _HEADING.match(line)
                if heading:
                    section = _BOLD.sub(r"\1", heading.group(1)).strip()
                    continue
                task = _TASK.match(line)
                if task:
                    tasks.append(Task(group, path.stem, section, short_title(task.group(1))))
    return tasks


def summary(tasks: list[Task]) -> str:
    """Pending count per area, e.g. 'pessoal/carreira: 21; empresa/dindin: 29'."""
    counts = Counter((t.group, t.area) for t in tasks)
    if not counts:
        return "nenhuma tarefa pendente encontrada"
    return "; ".join(f"{g}/{a}: {n}" for (g, a), n in sorted(counts.items()))


def _haystack(task: Task) -> str:
    return " ".join((fold(task.group), fold(task.area.replace("-", " ")), fold(task.section)))


def select(tasks: list[Task], words: list[str]) -> list[Task]:
    """Tasks whose group, area or section match the (accent-folded) words.

    Every word must match, so extra words narrow the list ("dindin feedback"); if nothing
    matches them all, fall back to tasks matching any word."""
    wanted = [fold(w) for w in words if w]
    if not wanted:
        return []
    strict = [t for t in tasks if all(w in _haystack(t) for w in wanted)]
    if strict:
        return strict
    return [t for t in tasks if any(w in _haystack(t) for w in wanted)]


SIMILARITY_CUTOFF = 0.72  # real typos scored 0.75-0.94, ordinary words stayed under 0.6


def vocabulary(tasks: list[Task]) -> set[str]:
    """Folded names a user may type: group, area (whole and by part) and section words."""
    words: set[str] = set()
    for task in tasks:
        words.add(fold(task.group))
        area = fold(task.area)
        words.add(area)
        words.update(p for p in area.split("-") if len(p) >= 3)
        words.update(w for w in re.findall(r"[a-z0-9]{4,}", fold(task.section)))
    return words


def _similar(a: str, b: str) -> float:
    if len(a) >= 3 and sorted(a) == sorted(b):  # transposed letters: "dmoo" -> "domo"
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def suggest(tasks: list[Task], word: str) -> str | None:
    """The closest known area or section word for a probable typo, or None."""
    target = fold(word)
    best, best_score = None, 0.0
    for candidate in vocabulary(tasks):
        score = _similar(target, candidate)
        if score > best_score:
            best, best_score = candidate, score
    return best if best_score >= SIMILARITY_CUTOFF else None


def resolve_query(tasks: list[Task], words: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Fix likely typos in the words of an explicit /tarefas query.

    A word that already matches something is kept; one that matches nothing is replaced by
    the closest known name. Returns the words to use and the (typed, used) corrections."""
    haystacks = [_haystack(t) for t in tasks]
    out: list[str] = []
    fixes: list[tuple[str, str]] = []
    for word in words:
        folded = fold(word)
        if any(folded in h for h in haystacks):
            out.append(word)
            continue
        guess = suggest(tasks, word)
        if guess and guess != folded:
            out.append(guess)
            fixes.append((word, guess))
        else:
            out.append(word)
    return out, fixes


def render_items(items: list[Task], limit: int = 25) -> str:
    lines = [f"- [{t.area} > {t.section}] {t.title}" if t.section else f"- [{t.area}] {t.title}" for t in items[:limit]]
    if len(items) > limit:
        lines.append(f"(+{len(items) - limit} não mostradas)")
    return "\n".join(lines)


def tasks_context(mind_dir: Path, words: list[str], limit: int = 25) -> str:
    """What the assistant is shown when asked about tasks: the chosen area's items, or counts."""
    tasks = load_pending(mind_dir)
    chosen = select(tasks, words)
    if chosen:
        return f"{len(chosen)} pendentes na área pedida:\n{render_items(chosen, limit)}"
    return f"Contagem de pendentes por área (o senhor não pediu uma área específica): {summary(tasks)}"
