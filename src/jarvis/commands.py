"""Parsing of messages that are handled by code instead of the model."""
from __future__ import annotations

import re

from .textutil import fold

# Two families of note requests. "anotar" is unambiguous, so polite or needy prefixes are fine
# ("pode anotar que...", "preciso anotar:"). "registrar/guardar/salvar" also mean other things
# ("guarda o notebook"), so they only count when followed by "isso" / "aí" / "pra mim".
_NOTE = re.compile(
    r"^\s*(?:"
    r"(?:(?:pode|poderia|consegue|voce pode|você pode|vc pode|quero|preciso|vou|gostaria de)\s+)*"
    r"(?:(?:me|mim)\s+)?(?:anota|anote|anotar)\b(?:\s+(?:isso|ai|aí|pra mim|para mim))*"
    r"|"
    r"(?:(?:pode|poderia|consegue|voce pode|você pode|vc pode)\s+)*"
    r"(?:registra|registre|registrar|guarda|guarde|guardar|salva|salve|salvar)\s+(?:isso|ai|aí|pra mim|para mim)"
    r"(?:\s+(?:ai|aí|pra mim|para mim))?"
    r"|"
    r"(?:n[aã]o|nunca)\s+esquec(?:e|a|er)\s+(?:de\s+)?que\b"  # "não esquece que o carro está na oficina": a note, not an alert
    r")[\s:,\-]*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
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


# "me lembra de pagar a luz amanhã às 9", also "pode lembrar ..." / "lembra eu ..." (a transcription or a typo drops the "me").
# A bare "lembra do que falei?" stays out: it is a question about memory.
_REMINDER = re.compile(
    r"^\s*(?:jarvis[\s,:]+)?(?:(?:pode\s+|poderia\s+)?me\s+(?:lembra|lembre|lembrar)|(?:lembra|lembre)-me"
    r"|(?:pode|poderia)\s+(?:lembra|lembre|lembrar)(?:\s+eu)?|(?:lembra|lembre)\s+eu)\b[\s:,\-]*(.*)$",
    re.IGNORECASE | re.DOTALL,
)


def parse_reminder_request(text: str) -> str | None:
    """Return what follows "me lembra" if the message starts a reminder request, else None."""
    match = _REMINDER.match(text)
    if not match:
        return None
    rest = match.group(1).strip()
    # "me lembre sim" answers an offer the assistant made; it is not a new request, so let it reach the model.
    return None if rest and is_yes(rest) else rest


# A reminder is only created when the user asked to be told something. A bare "tenho dentista
# amanhã às 14h" is a remark, not a request, whatever the model decides.
_REMINDER_INTENT = re.compile(
    r"\b(?:lembr\w*|avis\w*|alert\w*|notific\w*|desperta\w*|nao (?:me )?(?:deix\w*|esquec\w*))"
)


def has_reminder_intent(text: str) -> bool:
    return bool(_REMINDER_INTENT.search(fold(text)))


# The model picks the tool, but some tools change or hide things, so the code also wants the user's own words to
# ask for it: a misheard "Me lembro amanhã às 10 de correr" once made the model call "cancelar_lembrete 18".
_CANCEL_INTENT = re.compile(r"\b(?:cancel\w*|apag\w*|remov\w*|desmarc\w*|exclu\w*|delet\w*|esquec\w*|descart\w*|some\b|tir(?:a|e|ar)\b)")
_LIST_INTENT = re.compile(r"\b(?:lembretes?|marcad\w*|agendad\w*|compromiss\w*|avisos?|pendentes?|o que (?:eu )?(?:tenho|tem|esta)|quais)\b")
_CLEAR_INTENT = re.compile(r"\b(?:esquec\w*|limp\w*|recome\w*|zera\w*|apag\w*|comec\w* de novo)")
_NOTE_INTENT = re.compile(r"\b(?:anot\w*|registr\w*|guard\w*|salv\w*|notas?|esquec\w*|memoriz\w*|nao deixa)")
_MARK_INTENT = re.compile(r"\b(?:cheg\w*|sa(?:i|ir|ind\w*|iu|ida)\b|desci\b|descend\w*|embarq\w*|cheguei)")


def has_intent(action: str, text: str) -> bool:
    """Did the user's own words ask for this action? Only the actions that change things or may confuse are checked."""
    folded = fold(text)
    pattern = {"cancelar_lembrete": _CANCEL_INTENT, "listar_lembretes": _LIST_INTENT,
               "limpar_conversa": _CLEAR_INTENT, "anotar": _NOTE_INTENT, "avisar_marco": _MARK_INTENT}.get(action)
    if pattern is None:
        return True
    return bool(pattern.search(folded)) or (action in ("anotar", "avisar_marco") and is_yes(text))


_YES_WORDS = {
    "sim", "pode", "claro", "isso", "mesmo", "quero", "faz", "ok", "beleza", "blz", "bora", "manda", "ver", "pf", "pfv",
    "por", "favor", "me", "lembra", "lembre", "avisa", "avise", "jarvis", "senhor", "uhum", "aham", "positivo",
}
_YES_CORE = _YES_WORDS - {"me", "por", "favor", "jarvis", "senhor", "mesmo", "ver"}


def is_yes(text: str) -> bool:
    """A short agreement ("sim", "pode sim", "me lembre sim"), not a new request that merely contains one."""
    words = re.findall(r"[a-z]+", fold(text))
    return 0 < len(words) <= 6 and all(w in _YES_WORDS for w in words) and any(w in _YES_CORE for w in words)


_TASKS_REQUEST = re.compile(
    r"(?:^|\W)(?:tarefas?|pendencias?|afazeres|to-?do|o que (?:eu )?(?:tenho|preciso|falta)(?: que| pra| para)? fazer|o que (?:ainda )?(?:falta|resta)|o que tem (?:pra|para|que) fazer|pendentes?)\b"
)
_STOPWORDS = {
    "quais", "tarefas", "tarefa", "tenho", "pendencias", "pendencia", "pendentes", "pendente", "minhas",
    "minha", "meus", "preciso", "fazer", "para", "sobre", "qual", "tem", "hoje", "lista", "mostra",
    "mostre", "algo", "alguma", "algum", "ainda", "falta", "faltam", "todas", "todos", "favor", "pode",
    "voce", "agora", "aqui", "isso", "esse", "essa", "entao", "tipo", "coisa", "coisas", "semana",
    "amanha", "afazeres", "fazendo", "como", "estao", "estou", "ficou", "deve", "fala",
}


_CAPABILITIES = re.compile(
    r"(?:^|\W)(?:"
    r"o ?q(?:ue)? (?:voce|vc|tu) (?:pode|consegue|sabe|faz)(?: fazer)?|"
    r"(?:como|em que) (?:voce|vc|tu) (?:pode|consegue) (?:me )?ajudar|"
    r"(?:quais|qual) (?:sao )?(?:as |os )?(?:suas |seus )?(?:funcoes|funcionalidades|comandos|recursos|habilidades)|"
    r"(?:pra|para) que (?:voce|vc|tu) serve|"
    r"como (?:eu )?(?:uso|usa|usar) (?:voce|vc|isso|o bot|esse bot)|"
    r"(?:me )?(?:lista|mostra|mostre) (?:os |seus |todos os )?comandos"
    r")\b"
)
_BARE_HELP = re.compile(r"^\W*(?:ajuda|help|comandos|menu)\W*$")


def asks_capabilities(text: str) -> bool:
    """True for "o que você pode fazer?", "como pode me ajudar?", "quais são suas funções?", "ajuda"..."""
    folded = fold(text)
    if _BARE_HELP.match(folded):
        return True
    # Long messages are about something else ("o que você pode fazer com o meu deploy ...").
    return len(folded.split()) <= 9 and bool(_CAPABILITIES.search(folded))


def wants_tasks(text: str) -> bool:
    """True when the message asks about tasks/pending items."""
    return bool(_TASKS_REQUEST.search(fold(text)))


def task_query_words(text: str, min_len: int = 4) -> list[str]:
    """Words that may name an area or section ("tarefas de carreira" -> ["carreira"])."""
    return [w for w in re.findall(r"[a-z0-9]{%d,}" % min_len, fold(text)) if w not in _STOPWORDS]
