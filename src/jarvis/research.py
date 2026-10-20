"""Research requests ("pesquisa...", "investiga..."): ask where to look, then decide how deep to go.
Where to look (the Mind or the internet) is always the owner's choice: the code asks, never guesses.
On the internet a simple question is answered right away; a deep one goes to the Worker (stdlib only)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .textutil import fold

MIND, WEB = "mind", "web"
OFFER_MINUTES = 10
QUESTION = "No Mind ou por fora, na internet, senhor?"

_MIND_WORDS = re.compile(
    r"\b(?:no mind|nas? (?:minhas )?notas|nos? (?:meus )?(?:projetos|repos|repositorios|arquivos)|no vault|"
    r"nas? minhas tarefas|nos? meus documentos|no meu mind)\b"
)
_WEB_WORDS = re.compile(
    r"\b(?:na internet|na web|na rede|online|no google|pela internet|por fora|pesquisa externa|fora do mind)\b"
)
_ANSWER_MIND = re.compile(r"\b(?:mind|notas|vault|projetos|repos|repositorios|arquivos|meu|minhas?)\b")
_ANSWER_WEB = re.compile(r"\b(?:internet|web|rede|online|google|fora|externa|externo|net)\b")

# What makes a web question deep: comparing, analysing, surveying. The verbs "investiga" and "levanta" also mean it.
_DEEP = re.compile(
    r"\b(?:compar\w+|analis\w+|aprofund\w+|detalh\w+|relatorio|panorama|mercado|concorrentes?|pros e contras|"
    r"diferencas?|alternativas|tudo sobre|passo a passo|completo|completa|varios|varias|ranking|estudo|"
    r"investig\w+|levant\w+)\b"
)
DEEP_CHARS = 200


def scope_in_text(text: str) -> str | None:
    """Where the owner already said to look, in the request itself ("pesquisa na internet..."), if he did."""
    folded = fold(text)
    mind, web = bool(_MIND_WORDS.search(folded)), bool(_WEB_WORDS.search(folded))
    if mind == web:  # said both or neither: ask
        return None
    return MIND if mind else WEB


def parse_scope_answer(text: str) -> str | None:
    """The answer to the question: a short reply naming the Mind or the internet."""
    folded = fold(text)
    words = re.findall(r"[a-z]+", folded)
    if not 0 < len(words) <= 6:
        return None
    mind, web = bool(_ANSWER_MIND.search(folded)), bool(_ANSWER_WEB.search(folded))
    if mind == web:
        return None
    return MIND if mind else WEB


def is_deep(request: str) -> bool:
    """A deep web question goes to the Worker; the rest is a quick lookup."""
    return len(request) >= DEEP_CHARS or bool(_DEEP.search(fold(request)))


@dataclass
class _Offer:
    request: str
    expires: datetime


class Offers:
    """The research request waiting for the answer to "Mind or internet?", one per chat, expiring in 10 minutes;
    and the last quick answer, so a button can take it deeper."""

    def __init__(self) -> None:
        self._open: dict[int, _Offer] = {}
        self._last_quick: dict[int, str] = {}

    def offer(self, chat_id: int, request: str, now: datetime) -> None:
        self._open[chat_id] = _Offer(request, now + timedelta(minutes=OFFER_MINUTES))

    def pending(self, chat_id: int, now: datetime) -> str | None:
        found = self._open.get(chat_id)
        if found is None:
            return None
        if found.expires < now:
            del self._open[chat_id]
            return None
        return found.request

    def clear(self, chat_id: int) -> None:
        self._open.pop(chat_id, None)

    def remember_quick(self, chat_id: int, request: str) -> None:
        self._last_quick[chat_id] = request

    def last_quick(self, chat_id: int) -> str | None:
        return self._last_quick.get(chat_id)


# What the Jarvis says while a search runs and when it ends: the tools behind it (API, Worker) are never named.
ACKS = (
    "Deixe comigo, senhor; já estou procurando.",
    "Estou nisso, senhor. Volto assim que encontrar.",
    "Já estou investigando, senhor. Aviso quando tiver algo.",
    "Um momento, senhor; vou verificar isso.",
)
DONE_LINES = (
    "Terminei a pesquisa, senhor:",
    "Aqui está o que encontrei, senhor:",
    "Pronto, senhor. Isto é o que apurei:",
)
FAILED_LINE = "Não consegui concluir a pesquisa, senhor"
LATER_LINE = "Isso pede uma apuração mais cuidadosa, senhor; aviso assim que tiver algo."


def pick(pool: tuple[str, ...], n: int) -> str:
    """A line from the pool, rotating with `n` (a job id) so two in a row never repeat."""
    return pool[n % len(pool)]
