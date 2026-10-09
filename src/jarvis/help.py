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
    Command("tarefas", "[área]", "Pendências do seu Mind",
            "mostra as pendências do seu Mind por área; com uma área (ex.: /tarefas dindin) lista os itens, "
            "e palavras extras estreitam (/tarefas dindin feedback). Perdoa erro de digitação no nome da área."),
    Command("anota", "<texto>", "Guarda uma nota no inbox do Mind",
            'guarda uma nota no inbox do seu Mind. Também funciona em linguagem natural: "anota que preciso comprar pão".'),
    Command("desfaz", "", "Desfaz a última nota",
            "apaga a última nota que eu guardei no inbox do Mind."),
    Command("lembra", "<quando> <o quê>", "Marca um lembrete",
            'marca um lembrete que eu entrego no Telegram na hora certa. Ex.: /lembra amanhã às 9 pagar o aluguel; '
            '"hoje às 19 reunião, 10 min antes" avisa com antecedência; "daqui a 2 horas" também vale. '
            'Sem hora, assumo a padrão e aviso.'),
    Command("lembretes", "", "Lista os lembretes pendentes",
            "lista os lembretes pendentes, com o número de cada um."),
    Command("cancela", "<número>", "Cancela um lembrete",
            "cancela o lembrete de número dado (veja os números em /lembretes)."),
    Command("uso", "", "Gasto e chamadas de hoje",
            "mostra as chamadas, os tokens e o custo de hoje, com o teto diário."),
    Command("esquece", "", "Limpa a conversa",
            "limpa a conversa atual (também aceita /esquecer)."),
    Command("ajuda", "", "Lista o que eu sei fazer",
            "mostra esta lista."),
)

NATURAL_LANGUAGE = (
    'Pergunte "quais tarefas eu tenho?", "tarefas do dindin" ou "o que falta no domo" e eu respondo como no /tarefas (só leitura).',
    'Escreva "anota que ...", "pode anotar ..." ou "guarda isso: ..." e eu guardo a nota no inbox do Mind.',
    'Escreva "me lembra de ... amanhã às 9" e eu marco o lembrete, no mesmo formato do /lembra.',
    "Converso e tiro dúvidas no que eu sei.",
)
NOT_YET = "e-mail, agenda, áudio e controlar o computador"


def menu() -> list[tuple[str, str]]:
    """(command, description) pairs for the Telegram command menu."""
    return [(c.name, c.summary) for c in COMMANDS]


def format_help() -> str:
    """The help text, in Telegram HTML."""
    lines = ["<b>O que eu faço, senhor</b>", "", "<b>Comandos</b>"]
    for c in COMMANDS:
        usage = f"/{c.name}" + (f" {html.escape(c.args, quote=False)}" if c.args else "")
        lines.append(f"{usage} — {html.escape(c.detail, quote=False)}")
    lines += ["", "<b>Em linguagem natural</b>"]
    lines += [f"• {html.escape(text, quote=False)}" for text in NATURAL_LANGUAGE]
    lines += ["", f"<b>Ainda não faço:</b> {NOT_YET}."]
    return "\n".join(lines)
