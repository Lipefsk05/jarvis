"""The Mind's task board as the planner needs it: pending tasks with their markers (stdlib only, read-only).

Markers are the ones in tarefas/tarefas.md: 🔴🟡🟢 priority, 💡 idea, 📚 study (never in the daily plan), 📅 AAAA-MM-DD deadline, a trailing ^id,
⛓ depende de ^id, and ⏳ aguardando <quem/o quê> (waiting on someone: never planned, never a "slip", listed apart). Two optional ones say *where* and *how long*: 📱 (phone is enough), 💻 (needs the
notebook) and ⏱ 30min / ⏱ 2h. Without a marker, where is guessed from the words ("ligar", "pagar", "estudar"
= phone) and defaults to the notebook, so nothing heavy is ever sent to the bus by accident. Only the board is
read here; deciding what goes in the day is the planner's job.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .mind import GROUPS, INDEX_FILES, short_title
from .plan import NOTEBOOK, PHONE
from .textutil import fold

HIGH, MEDIUM, LOW, UNRANKED = "alta", "media", "baixa", "sem"
_PRIORITY = {"🔴": HIGH, "🟡": MEDIUM, "🟢": LOW}

_TASK = re.compile(r"^(\s*)- \[ \]\s+(.*)$")
_HEADING = re.compile(r"^##\s+(.*)$")
_ID = re.compile(r"\s\^([a-z0-9][a-z0-9-]*)\s*$")
_DUE = re.compile(r"📅\s*(\d{4})-(\d{2})-(\d{2})")
_DEPENDS = re.compile(r"⛓\s*depende\s+(?:de|do|da)\b([^.;\n]*)")
_REF = re.compile(r"\^([a-z0-9][a-z0-9-]*)")
_WAITING = re.compile(r"⏳\s*(?:aguardando\s+)?([^.;\n^]*)")
_MINUTES = re.compile(r"⏱\s*(\d+)\s*(min|m|h)\b")
_BOLD = re.compile(r"\*\*(.+?)\*\*")

# Words (accent-folded, matched at the start of a word) that mean the task can be done from the phone: talk, buy,
# pay, read, decide...
_PHONE = re.compile(
    r"\b(?:ligar|telefonar|comprar|pagar|agendar|perguntar|pedir|responder|mandar mensagem|enviar mensagem|avisar|"
    r"confirmar|estudar|ler|assistir|ouvir|pesquisar|decidir|escolher|renovar|cancelar|assinar|mudar quem paga)\b"
)
# ...unless the same title clearly needs code or a computer.
_NOTEBOOK = re.compile(
    r"\b(?:codigo|codar|implementar|programar|deploy|publicar|build|refator\w*|commit|testes?|script|criar app|"
    r"configurar|instalar|migrar|landing|site|repo|firebase|flutter|documentar|escrever|design|figma|prototipo|"
    r"interface|jarvis|mind)\b"
)
TITLE_CHARS = 90  # the guess reads only the lead of the task: descriptions are full of unrelated verbs


@dataclass(frozen=True)
class BoardTask:
    group: str          # "pessoal" | "empresa"
    area: str           # file stem
    section: str
    title: str          # short, for showing
    depth: int          # 0 = top-level bullet, 1+ = indented sub-item
    priority: str       # HIGH | MEDIUM | LOW | UNRANKED
    idea: bool          # 💡: never planned, only recalled now and then
    due: date | None
    task_id: str        # trailing ^id, "" if none
    depends: tuple[str, ...]  # ids it waits for
    waits: bool         # ⛓ with no id: waiting for something outside the board
    needs: str          # NOTEBOOK | PHONE
    needs_marked: bool  # needs came from 📱/💻, not from the word guess
    minutes: int        # 0 = unknown
    study: bool = False  # 📚: waits for a study plan, never in the daily plan
    waiting_for: str = ""  # ⏳: who or what the task waits for ("o Pedro aprovar a proposta"); implies `waits`

    @property
    def key(self) -> str:
        """Stable id for the plan: the board's ^id, else a short hash of area and title."""
        if self.task_id:
            return f"^{self.task_id}"
        digest = hashlib.sha1(f"{self.group}/{self.area}/{self.title}".encode()).hexdigest()[:8]
        return f"{self.area}:{digest}"


def guess_needs(text: str) -> str:
    """Where a task can be done, from the lead of its title. Computer words win over phone words; no clue = notebook."""
    folded = " ".join(fold(text[:TITLE_CHARS]).split())
    if _NOTEBOOK.search(folded):
        return NOTEBOOK
    return PHONE if _PHONE.search(folded) else NOTEBOOK


def _minutes(text: str) -> int:
    found = _MINUTES.search(text)
    if not found:
        return 0
    amount = int(found.group(1))
    return amount * 60 if found.group(2) == "h" else amount


def parse_task(group: str, area: str, section: str, indent: str, body: str) -> BoardTask:
    """One `- [ ]` bullet (without the checkbox) as a BoardTask."""
    ident = _ID.search(body)
    task_id = ident.group(1) if ident else ""
    text = body[:ident.start()] if ident else body
    lead = text[:14]  # the priority emoji sits right after the checkbox
    priority = next((p for emoji, p in _PRIORITY.items() if emoji in lead), UNRANKED)
    idea = "💡" in lead
    study = "📚" in lead
    due = None
    due_match = _DUE.search(text)
    if due_match:
        try:
            due = date(*(int(g) for g in due_match.groups()))
        except ValueError:
            due = None
    depends: tuple[str, ...] = ()
    waits = False
    dep = _DEPENDS.search(text)
    if dep:
        depends = tuple(dict.fromkeys(_REF.findall(dep.group(1))))
        waits = not depends
    waiting = _WAITING.search(text)
    waiting_for = " ".join(waiting.group(1).split()).strip(" ,") if waiting else ""
    if waiting:
        waits = True  # "⏳ ..." is the explicit way to say it: out of the plan, without counting as a slip
    plain = _BOLD.sub(r"\1", text)
    if "📱" in text:
        needs, marked = PHONE, True
    elif "💻" in text:
        needs, marked = NOTEBOOK, True
    else:
        needs, marked = guess_needs(plain), False
    return BoardTask(
        group, area, section, short_title(_clean(text)), len(indent) // 2, priority, idea, due, task_id, depends,
        waits, needs, marked, _minutes(text), study, waiting_for,
    )


def _clean(text: str) -> str:
    """Drop the markers so the title reads as a sentence."""
    text = _DUE.sub("", text)
    text = _DEPENDS.sub("", text)
    text = _WAITING.sub("", text)
    text = _MINUTES.sub("", text)
    for symbol in ("🔴", "🟡", "🟢", "💡", "📚", "📱", "💻", "⛓", "⏳"):
        text = text.replace(symbol, "")
    return text.strip()


def load_board(mind_dir: Path) -> list[BoardTask]:
    """Every pending `- [ ]` bullet under tarefas/pessoal and tarefas/empresa, markers parsed."""
    tasks: list[BoardTask] = []
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
                    tasks.append(parse_task(group, path.stem, section, task.group(1), task.group(2)))
    return tasks


def blocked(task: BoardTask, open_ids: set[str]) -> bool:
    """Waiting on something: an outside condition, or a board task that is still open."""
    return task.waits or any(dep in open_ids for dep in task.depends)


def split(tasks: list[BoardTask], today: date) -> dict[str, list[BoardTask]]:
    """The three buckets of the planner: `prioridade` (high, or a deadline within a week), `lista` (the rest,
    rises when there is room) and `ideias` and `estudos` (never planned: ideas are only recalled, study waits for its own plan). Blocked tasks are left out of `prioridade`."""
    open_ids = {t.task_id for t in tasks if t.task_id}
    buckets: dict[str, list[BoardTask]] = {"prioridade": [], "lista": [], "ideias": [], "estudos": []}
    for task in tasks:
        if task.idea:
            buckets["ideias"].append(task)
        elif task.study:
            buckets["estudos"].append(task)
        elif not blocked(task, open_ids) and (task.priority == HIGH or (task.due and (task.due - today).days <= 7)):
            buckets["prioridade"].append(task)
        else:
            buckets["lista"].append(task)
    buckets["prioridade"].sort(key=lambda t: (t.due or date.max, t.priority != HIGH, t.title))
    return buckets
