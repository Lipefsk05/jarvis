"""What the model may ask the system to do. The model only *names* an action; the code
validates the arguments and runs the matching handler (stdlib only)."""
from __future__ import annotations

from dataclasses import dataclass

from .talker.base import ToolCall

MAX_NOTE_CHARS = 2000
MAX_AREA_CHARS = 80


def _tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
        },
    }


TOOLS = [
    _tool(
        "anotar",
        "Guarda uma nota no inbox do Mind do senhor. Chame SOMENTE quando ele pedir explicitamente, com as palavras que "
        "usar, para anotar, registrar, guardar, fazer uma nota ou não esquecer algo (\"não esquece que...\"), ou quando "
        "ele confirmar (\"sim\", \"pode\") uma oferta sua de anotar. Um comentário solto (\"preciso comprar pão\") é "
        "conversa, não pedido de nota. Não é lembrete com alerta: isso ainda não existe.",
        {"texto": {"type": "string", "description": "O conteúdo da nota, curto e sem o verbo (nada de \"anota que\")."}},
        ["texto"],
    ),
    _tool(
        "consultar_tarefas",
        "Mostra as tarefas pendentes do Mind do senhor (somente leitura). Chame quando ele perguntar o que tem "
        "pendente, a fazer ou por fazer, de tudo ou de uma área ou projeto.",
        {"area": {"type": "string", "description": "Área ou projeto citado (ex.: dindin, carreira). Vazio para o resumo por área."}},
    ),
    _tool("ver_gasto", "Mostra as chamadas, os tokens e o custo de hoje, com o teto diário. Chame quando o senhor perguntar quanto gastou ou usou."),
    _tool("mostrar_ajuda", "Mostra a lista do que o assistente sabe fazer. Chame quando o senhor perguntar o que você faz, como usar você, quais são seus comandos ou funções, ou pedir ajuda com o próprio assistente."),
    _tool("limpar_conversa", "Apaga o histórico da conversa atual. Chame quando o senhor pedir para esquecer ou recomeçar a conversa."),
]
KNOWN = {t["function"]["name"] for t in TOOLS}


@dataclass(frozen=True)
class Action:
    name: str
    texto: str = ""
    area: str = ""


def _clean(value: object, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def parse_action(call: ToolCall | None) -> Action | None:
    """Turn a model tool call into a validated Action, or None if it is unknown or malformed."""
    if call is None or call.name not in KNOWN or not isinstance(call.arguments, dict):
        return None
    if call.name == "anotar":
        texto = _clean(call.arguments.get("texto"), MAX_NOTE_CHARS)
        return Action("anotar", texto=texto) if texto else None
    if call.name == "consultar_tarefas":
        return Action("consultar_tarefas", area=_clean(call.arguments.get("area"), MAX_AREA_CHARS))
    return Action(call.name)
