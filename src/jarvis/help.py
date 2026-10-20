"""The one list of commands: feeds /ajuda, the answer to "o que você pode fazer?" and the
Telegram command menu, so they can never disagree (stdlib only)."""
from __future__ import annotations

import html
from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    name: str     # Telegram command, lowercase ASCII
    args: str     # argument hint shown in the help, "" when none
    summary: str  # short text for the Telegram "/" menu (max 256 chars)
    detail: str   # what it does, for the help text


COMMANDS = (
    Command("tarefas", "[área]", "Pendências do seu Mind", "pendências do Mind, por área."),
    Command("plano", "[semana]", "O plano de hoje", "tarefas de hoje; com \"semana\", os próximos dias."),
    Command("agenda", "[dia]", "A agenda do Google", "compromissos das 3 agendas; sem dia, hoje."),
    Command("anota", "<texto>", "Guarda uma nota no inbox do Mind", "guarda uma nota no inbox."),
    Command("pede", "<pedido>", "Pede ao Trabalhador (Claude Code)", "o Trabalhador pesquisa no Mind em segundo plano e avisa quando termina; só leitura."),
    Command("pedidos", "", "Pedidos ao Trabalhador", "lista os últimos pedidos ao Trabalhador."),
    Command("desfaz", "", "Desfaz a última nota", "apaga a última nota que guardei."),
    Command("lembra", "<quando> <o quê>", "Marca um lembrete", "marca um lembrete."),
    Command("lembretes", "", "Lista os lembretes pendentes", "lista os lembretes, com número."),
    Command("cancela", "<número>", "Cancela um lembrete", "cancela o lembrete pelo número."),
    Command("uso", "", "Gasto e chamadas de hoje", "chamadas, tokens e custo de hoje."),
    Command("esquece", "", "Limpa a conversa", "limpa a conversa atual."),
    Command("ajuda", "", "Lista o que eu sei fazer", "mostra esta lista."),
)

# (what it is, a short example of how to say it)
NATURAL_LANGUAGE = (
    ("Ver tarefas", "quais tarefas eu tenho do dindin?"),
    ("Anotar", "anota que preciso comprar pão"),
    ("Lembrete", "me lembra amanhã às 9 de pagar o aluguel"),
    ("Lembrete que repete", "toda segunda às 9 reunião"),
    ("Concluir tarefa", "concluí a landing do dindin"),
    ("Áudio", "mande um áudio e eu respondo como se fosse texto"),
    ("Conversa", "tire dúvidas comigo no que eu sei"),
)
AGENDA_LANGUAGE = (
    ("Ver a agenda", "o que eu tenho amanhã?"),
    ("Marcar na agenda", "marca reunião com o cliente sexta às 15"),
    ("Mover ou cancelar", "muda o dentista pra segunda às 10"),
)
NOT_YET = "e-mail, responder em áudio e controlar o computador (o Trabalhador só lê)"


def menu() -> list[tuple[str, str]]:
    """(command, description) pairs for the Telegram command menu."""
    return [(c.name, c.summary) for c in COMMANDS]


def format_help(agenda: bool = False) -> str:
    """The help text, in Telegram HTML: the commands first, then the natural-language phrases, each on its own line."""
    lines = ["<b>Comandos</b>"]
    for c in COMMANDS:
        usage = f"/{c.name}" + (f" {html.escape(c.args, quote=False)}" if c.args else "")
        lines.append(f"{usage} — {html.escape(c.detail, quote=False)}")
    lines += ["", "<b>Em linguagem natural</b>"]
    for what, example in NATURAL_LANGUAGE + (AGENDA_LANGUAGE if agenda else ()):
        lines += ["", f"<b>{html.escape(what, quote=False)}</b>", f"“{html.escape(example, quote=False)}”"]
    lines += ["", f"<b>Ainda não faço:</b> {NOT_YET}."]
    return "\n".join(lines)
