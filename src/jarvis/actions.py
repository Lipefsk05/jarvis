"""What the model may ask the system to do. The model only *names* an action; the code
validates the arguments and runs the matching handler (stdlib only)."""
from __future__ import annotations

from dataclasses import dataclass

from .talker.base import ToolCall

MAX_NOTE_CHARS = 2000
MAX_AREA_CHARS = 80
MAX_WHEN_CHARS = 80
MAX_LEAD_MINUTES = 24 * 60
MAX_EVENT_MINUTES = 24 * 60
MAX_REF_CHARS = 400
AGENDA_TOOLS = frozenset({"consultar_agenda", "criar_evento", "mover_evento", "cancelar_evento"})


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
        "com as palavras dele, inclusive a repetição se houver (\"todo dia às 8\", \"toda segunda às 9\", \"nos dias úteis às 8\").",
        {
            "texto": {"type": "string", "description": "O que lembrar, curto, sem o pedido (\"pg jovem\", \"pagar o aluguel\")."},
            "quando": {"type": "string", "description": "O momento nas palavras do senhor: \"amanhã às 9\", \"hoje às 19\", \"daqui a 2 horas\", ou repetindo: \"todo dia às 8\", \"toda segunda às 9\". Sem hora dita, só o dia."},
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
    _tool(
        "concluir_tarefa",
        "Registra que o senhor terminou uma tarefa do plano. Chame quando ele disser que concluiu, terminou, fez ou "
        "finalizou algo (\"concluí a landing\", \"terminei o relatório\", \"fiz o cadastro\"). Não chame para o que "
        "ele ainda vai fazer, nem para um comentário sobre o que outra pessoa fez.",
        {"tarefa": {"type": "string", "description": "As palavras dele sobre qual tarefa foi concluída, curtas (\"landing do dindin\")."}},
        ["tarefa"],
    ),
    _tool(
        "consultar_agenda",
        "Mostra os compromissos da agenda do Google do senhor (as três contas juntas), somente leitura. Chame quando "
        "ele perguntar o que tem na agenda, que compromissos ou reuniões tem, ou se está livre num dia. Não é a lista "
        "de tarefas do Mind nem os lembretes.",
        {"quando": {"type": "string", "description": "O dia nas palavras dele: \"hoje\", \"amanhã\", \"sexta\", \"dia 20\", \"essa semana\". Vazio para hoje."}},
    ),
    _tool(
        "criar_evento",
        "Marca um compromisso na agenda do Google do senhor (com hora e duração; diferente de lembrete, que é só um "
        "aviso). Chame quando ele pedir para marcar, agendar ou pôr na agenda uma reunião, consulta, evento ou "
        "compromisso. Um compromisso só contado (\"tenho dentista amanhã\") é conversa. Nunca calcule datas: passe o "
        "momento com as palavras dele.",
        {
            "titulo": {"type": "string", "description": "O que é, curto (\"Reunião com o cliente\", \"Dentista\")."},
            "quando": {"type": "string", "description": "O momento nas palavras do senhor: \"amanhã às 15\", \"sexta às 10h\"."},
            "duracao_minutos": {"type": ["integer", "null"], "description": "Só se ele disser quanto dura: \"por 2 horas\" = 120."},
            "conta": {"type": ["string", "null"], "description": "Só se ele DISSE em qual agenda: pessoal, trabalho (profissional) ou Café. Nunca pergunte nem escolha: sem ele dizer, deixe vazio e o sistema pergunta."},
        },
        ["titulo", "quando"],
    ),
    _tool(
        "mover_evento",
        "Muda o dia ou a hora de um compromisso que já está na agenda do Google. Chame quando o senhor pedir para "
        "mover, remarcar, adiar, antecipar ou passar um compromisso para outro momento.",
        {
            "busca": {"type": "string", "description": "Palavras do título do compromisso (\"reunião com o cliente\")."},
            "quando": {"type": "string", "description": "O novo momento nas palavras dele: \"sexta às 10\"."},
        },
        ["busca", "quando"],
    ),
    _tool(
        "cancelar_evento",
        "Apaga um compromisso da agenda do Google. Chame quando o senhor pedir para cancelar, apagar ou desmarcar um "
        "compromisso, reunião ou evento da agenda (não um lembrete).",
        {"busca": {"type": "string", "description": "Palavras do título do compromisso."}},
        ["busca"],
    ),
    _tool(
        "delegar_trabalho",
        "Passa ao Trabalhador (Claude Code, só leitura, em segundo plano) uma pesquisa que exige ler arquivos do Mind do "
        "senhor. Chame SOMENTE quando ele pedir com um verbo de investigação (pesquisa, investiga, procura, descobre, "
        "levanta) algo que precisa de busca nas notas, tarefas ou projetos. Pergunta rápida que você responde com o que "
        "já sabe, conversa e pedido de tarefas, agenda ou lembretes não são isso.",
        {"pedido": {"type": "string", "description": "O que pesquisar, nas palavras do senhor, completo o bastante para quem não viu a conversa."}},
        ["pedido"],
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
    tarefa: str = ""  # which task he says he finished
    duracao: int = 0  # minutes an event lasts (0 = not said)
    conta: str = ""  # which calendar he named, in his words
    ref: str = ""  # set by the code once an event was found and confirmed: "trabalho:id1;cafe:id2"


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
    if call.name == "concluir_tarefa":
        tarefa = _clean(call.arguments.get("tarefa"), MAX_NOTE_CHARS)
        return Action("concluir_tarefa", tarefa=tarefa) if tarefa else None
    if call.name == "consultar_agenda":
        return Action("consultar_agenda", quando=_clean(call.arguments.get("quando"), MAX_WHEN_CHARS))
    if call.name == "criar_evento":
        texto, quando = _clean(call.arguments.get("titulo"), MAX_NOTE_CHARS), _clean(call.arguments.get("quando"), MAX_WHEN_CHARS)
        minutes = _int(call.arguments["duracao_minutos"]) if call.arguments.get("duracao_minutos") not in (None, "") else 0
        if not texto or not quando or minutes is None or not 0 <= minutes <= MAX_EVENT_MINUTES:
            return None
        return Action("criar_evento", texto=texto, quando=quando, duracao=minutes,
                      conta=_clean(call.arguments.get("conta"), MAX_AREA_CHARS))
    if call.name == "mover_evento":
        busca, quando = _clean(call.arguments.get("busca"), MAX_AREA_CHARS), _clean(call.arguments.get("quando"), MAX_WHEN_CHARS)
        return Action("mover_evento", busca=busca, quando=quando) if busca and quando else None
    if call.name == "delegar_trabalho":
        pedido = _clean(call.arguments.get("pedido"), MAX_NOTE_CHARS)
        return Action("delegar_trabalho", texto=pedido) if pedido else None
    if call.name == "cancelar_evento":
        busca = _clean(call.arguments.get("busca"), MAX_AREA_CHARS)
        return Action("cancelar_evento", busca=busca) if busca else None
    return Action(call.name)
