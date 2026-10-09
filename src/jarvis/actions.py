"""What the model may ask the system to do. The model only *names* an action; the code
validates the arguments and runs the matching handler (stdlib only)."""
from __future__ import annotations

from dataclasses import dataclass

from .talker.base import ToolCall

MAX_NOTE_CHARS = 2000
MAX_AREA_CHARS = 80
MAX_WHEN_CHARS = 80
MAX_LEAD_MINUTES = 24 * 60


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
    _tool(
        "criar_lembrete",
        "Marca um lembrete que o sistema entrega na hora. Chame quando o senhor pedir para ser lembrado ou avisado de "
        "algo num momento (\"me lembra\", \"me avisa\", \"não me deixa esquecer\" com dia ou hora). Um compromisso "
        "só contado (\"tenho dentista amanhã\") é conversa, não pedido de aviso. Nunca calcule datas: passe o momento "
        "com as palavras dele.",
        {
            "texto": {"type": "string", "description": "O que lembrar, curto, sem o pedido (\"pg jovem\", \"pagar o aluguel\")."},
            "quando": {"type": "string", "description": "O momento nas palavras do senhor: \"amanhã às 9\", \"hoje às 19\", \"daqui a 2 horas\". Sem hora dita, só o dia."},
            "antecedencia_minutos": {"type": ["integer", "null"], "description": "Só se ele pedir aviso antes do momento: \"10 min antes\" = 10, \"meia hora antes\" = 30, \"1 hora antes\" = 60."},
        },
        ["texto", "quando"],
    ),
    _tool("listar_lembretes", "Mostra os lembretes pendentes. Chame quando o senhor perguntar quais lembretes tem ou o que está marcado para avisar. Não é a lista de tarefas do Mind."),
    _tool(
        "cancelar_lembrete",
        "Cancela um lembrete pendente. Chame quando o senhor pedir para cancelar, apagar ou desmarcar um lembrete.",
        {
            "numero": {"type": ["integer", "null"], "description": "O número do lembrete, se ele disse."},
            "busca": {"type": ["string", "null"], "description": "Palavras do texto do lembrete, se ele não disse o número (\"aluguel\")."},
        },
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
    quando: str = ""
    antecedencia: int = 0  # minutes of advance warning
    numero: int = 0
    busca: str = ""


def _clean(value: object, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _int(value: object) -> int | None:
    """An integer from what the model sent (an int, an integral float or digits), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def parse_action(call: ToolCall | None) -> Action | None:
    """Turn a model tool call into a validated Action, or None if it is unknown or malformed."""
    if call is None or call.name not in KNOWN or not isinstance(call.arguments, dict):
        return None
    if call.name == "anotar":
        texto = _clean(call.arguments.get("texto"), MAX_NOTE_CHARS)
        return Action("anotar", texto=texto) if texto else None
    if call.name == "consultar_tarefas":
        return Action("consultar_tarefas", area=_clean(call.arguments.get("area"), MAX_AREA_CHARS))
    if call.name == "criar_lembrete":
        texto, quando = _clean(call.arguments.get("texto"), MAX_NOTE_CHARS), _clean(call.arguments.get("quando"), MAX_WHEN_CHARS)
        lead = _int(call.arguments["antecedencia_minutos"]) if call.arguments.get("antecedencia_minutos") not in (None, "") else 0
        if not texto or not quando or lead is None or not 0 <= lead <= MAX_LEAD_MINUTES:
            return None
        return Action("criar_lembrete", texto=texto, quando=quando, antecedencia=lead)
    if call.name == "cancelar_lembrete":
        numero = _int(call.arguments["numero"]) if call.arguments.get("numero") not in (None, "") else 0
        busca = _clean(call.arguments.get("busca"), MAX_AREA_CHARS)
        if numero is None or numero < 0 or not (numero or busca):
            return None
        return Action("cancelar_lembrete", numero=numero, busca=busca)
    return Action(call.name)
