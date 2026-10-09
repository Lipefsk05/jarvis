"""The /uso screen: which AI answers, how much each did today and how much is left (stdlib only)."""
from __future__ import annotations

import html

NAMES = {"groq": "Groq", "gemini": "Gemini", "anthropic": "Claude (Anthropic)"}
# Facts we measured but the API does not report; shown next to the provider so "how much is left" is honest.
QUOTA_NOTES = {
    "gemini": "plano grátis: cerca de 5 pedidos por minuto (medido); o teto diário não é informado",
}


def _n(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _usd(value: float, places: int) -> str:
    return f"US$ {value:.{places}f}".replace(".", ",")


def _name(provider: str) -> str:
    return NAMES.get(provider, provider)


def _limits_line(limits: dict) -> str:
    parts = []
    if limits.get("requests_remaining") is not None and limits.get("requests_limit"):
        parts.append(f"restam {_n(limits['requests_remaining'])} de {_n(limits['requests_limit'])} pedidos hoje")
    if limits.get("tokens_remaining") is not None and limits.get("tokens_limit"):
        parts.append(f"{_n(limits['tokens_remaining'])} de {_n(limits['tokens_limit'])} tokens neste minuto")
    line = "; ".join(parts) or "limites não informados"
    suffix = f" (lido na última resposta, às {limits['at']})" if limits.get("at") else ""
    return f"{line}{suffix}. O teto diário de tokens não é informado pela API"


def format_usage(report: dict, info: list[dict]) -> str:
    """HTML for Telegram. `report` comes from Budget.report(), `info` from ChainTalker.info()."""
    lines = ["<b>Uso de hoje</b>", ""]
    if info:
        main = info[0]
        lines.append(f"<b>IA em uso:</b> {_name(main['name'])}" + (f" · {html.escape(main['model'], quote=False)}" if main["model"] else ""))
        backups = info[1:]
        if backups:
            lines.append("<b>Reserva:</b> " + ", ".join(
                _name(b["name"]) + (f" · {html.escape(b['model'], quote=False)}" if b["model"] else "") for b in backups))
        else:
            lines.append("<b>Reserva:</b> nenhuma ligada")
    if report.get("last_provider"):
        lines.append(f"<b>Última resposta:</b> {_name(report['last_provider'])}")

    lines += ["", f"<b>Chamadas:</b> {_n(report['calls'])} · {_n(report['input'])} tokens de entrada · {_n(report['output'])} de saída"]
    for provider, entry in sorted(report["providers"].items()):
        lines.append(f"• {_name(provider)} — {_n(entry['calls'])} chamadas")

    all_free = bool(info) and all(i["free"] for i in info)
    cost = _usd(report["cost"], 4)
    lines += ["", f"<b>Custo:</b> {cost}" + (" (todos os provedores ligados são grátis)" if all_free else "")]
    cap = report.get("cap")
    if cap:
        used = report["cost"] / cap * 100
        lines.append(f"<b>Teto diário:</b> {_usd(cap, 2)} — usado {used:.0f}%, restam {_usd(max(cap - report['cost'], 0), 2)}")

    if info:
        lines += ["", "<b>Quanto ainda posso usar</b>"]
        for item in info:
            name = _name(item["name"])
            if item["limits"]:
                lines.append(f"• {name}: {_limits_line(item['limits'])}.")
            elif item["name"] in QUOTA_NOTES:
                lines.append(f"• {name}: {QUOTA_NOTES[item['name']]}.")
            elif item["free"]:
                lines.append(f"• {name}: grátis; ainda sem dados de limite (aparecem depois da primeira resposta).")
            else:
                lines.append(f"• {name}: pago, limitado pelo teto diário acima.")
    return "\n".join(lines)
