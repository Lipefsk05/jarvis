"""Parsing of messages that are handled by code instead of the model."""
from __future__ import annotations

import re

from .textutil import fold

_NOTE = re.compile(r"^\s*(?:anota|anote|anotar)\b[\s:,\-]*(.*)$", re.IGNORECASE | re.DOTALL)
# "anota que preciso comprar queijo" -> the filler "que" is not part of the note.
_FILLER = re.compile(r"^(?:que|aí|ai)\b[\s:,\-]*", re.IGNORECASE)


def parse_note_request(text: str) -> str | None:
    """Return the text to save if the message is a note request, else None.

    "anota comprar café" -> "comprar café"; a bare "anota" -> "" (ask what to note);
    "anotaram tudo" or any other sentence -> None (goes to the model).
    """
    match = _NOTE.match(text)
    if not match:
        return None
    return _FILLER.sub("", match.group(1).strip()).strip()


_TASKS_REQUEST = re.compile(
    r"(?:^|\W)(?:tarefas?|pendencias?|afazeres|to-?do|o que (?:eu )?(?:tenho|preciso|falta)(?: que| pra| para)? fazer|pendentes?)\b"
)
_STOPWORDS = {
    "quais", "tarefas", "tarefa", "tenho", "pendencias", "pendencia", "pendentes", "pendente", "minhas",
    "minha", "meus", "preciso", "fazer", "para", "sobre", "qual", "tem", "hoje", "lista", "mostra",
    "mostre", "algo", "alguma", "algum", "ainda", "falta", "faltam", "todas", "todos", "favor", "pode",
    "voce", "agora", "aqui", "isso", "esse", "essa", "entao", "tipo", "coisa", "coisas", "semana",
    "amanha", "afazeres", "fazendo", "como", "estao", "estou", "ficou", "deve", "fala",
}


def wants_tasks(text: str) -> bool:
    """True when the message asks about tasks/pending items."""
    return bool(_TASKS_REQUEST.search(fold(text)))


def task_query_words(text: str, min_len: int = 4) -> list[str]:
    """Words that may name an area or section ("tarefas de carreira" -> ["carreira"])."""
    return [w for w in re.findall(r"[a-z0-9]{%d,}" % min_len, fold(text)) if w not in _STOPWORDS]
