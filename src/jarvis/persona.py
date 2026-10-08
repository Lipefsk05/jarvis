"""Loads the Talker prompt from persona/jarvis.md and fills the runtime placeholders."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

WEEKDAYS = (
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
)
NO_STATE = "(nenhum estado registrado ainda)"
NO_SUMMARY = "(conversa recém-iniciada)"
NO_HINT = "(nenhuma)"
NO_TASKS = "(o senhor não perguntou por tarefas nesta mensagem)"


def load_template(path: Path) -> str:
    """Return the prompt body: everything after the first line that is exactly '---'."""
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "---":
            return "\n".join(lines[index + 1:]).strip()
    return "\n".join(lines).strip()


def format_now(now: datetime) -> str:
    return f"{WEEKDAYS[now.weekday()]}, {now:%d/%m/%Y %H:%M}"


def render(
    template: str,
    *,
    humor_allowed: bool,
    now: datetime,
    estado_atual: str = "",
    resumo: str = "",
    tarefas: str = "",
    dica: str = "",
) -> str:
    replacements = {
        "{{humor_permitido}}": "SIM, mas a maioria das respostas NÃO deve ter piada: só faça uma se for realmente boa e ligada a um fato real" if humor_allowed else "NÃO",
        "{{data_hora}}": format_now(now),
        "{{estado_atual}}": estado_atual.strip() or NO_STATE,
        "{{resumo_conversa}}": resumo.strip() or NO_SUMMARY,
        "{{tarefas_mind}}": tarefas.strip() or NO_TASKS,
        "{{dica_de_estilo}}": dica.strip() or NO_HINT,
    }
    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)
    return template
