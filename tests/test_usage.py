import unittest

from jarvis.usage import format_usage

REPORT = {
    "date": "2026-10-09", "calls": 55, "input": 92091, "output": 3196, "cost": 0.0, "cap": 1.0,
    "providers": {"groq": {"calls": 50, "input": 1, "output": 1, "cost": 0.0}, "gemini": {"calls": 5, "input": 1, "output": 1, "cost": 0.0}},
    "last_provider": "groq",
}
GROQ = {"name": "groq", "model": "openai/gpt-oss-120b", "free": True,
        "limits": {"requests_limit": 1000, "requests_remaining": 945, "tokens_limit": 8000, "tokens_remaining": 7200, "at": "14:32"}}
GEMINI = {"name": "gemini", "model": "gemini-2.5-flash", "free": True, "limits": None}


class UsageScreenTest(unittest.TestCase):
    def test_shows_which_ai_answers_and_the_backup(self):
        text = format_usage(REPORT, [GROQ, GEMINI])
        self.assertIn("<b>IA em uso:</b> Groq · openai/gpt-oss-120b", text)
        self.assertIn("<b>Reserva:</b> Gemini · gemini-2.5-flash", text)
        self.assertIn("<b>Última resposta:</b> Groq", text)

    def test_totals_use_brazilian_number_format_and_a_per_provider_split(self):
        text = format_usage(REPORT, [GROQ, GEMINI])
        self.assertIn("55 · 92.091 tokens de entrada · 3.196 de saída", text)
        self.assertIn("• Groq — 50 chamadas", text)
        self.assertIn("• Gemini — 5 chamadas", text)

    def test_cost_and_cap(self):
        text = format_usage(REPORT, [GROQ, GEMINI])
        self.assertIn("<b>Custo:</b> US$ 0,0000 (todos os provedores ligados são grátis)", text)
        self.assertIn("<b>Teto diário:</b> US$ 1,00 — usado 0%, restam US$ 1,00", text)
        paid = dict(REPORT, cost=0.25)
        text = format_usage(paid, [GROQ, {"name": "anthropic", "model": "claude-haiku-5-5", "free": False, "limits": None}])
        self.assertIn("US$ 0,2500", text)
        self.assertNotIn("todos os provedores ligados são grátis", text)
        self.assertIn("usado 25%, restam US$ 0,75", text)

    def test_how_much_is_left_comes_from_the_real_limits(self):
        text = format_usage(REPORT, [GROQ, GEMINI])
        self.assertIn("restam 945 de 1.000 pedidos hoje; 7.200 de 8.000 tokens neste minuto (lido na última resposta, às 14:32)", text)
        self.assertIn("O teto diário de tokens não é informado", text)
        self.assertIn("• Gemini: plano grátis: cerca de 5 pedidos por minuto", text)

    def test_before_the_first_answer_there_are_no_limits_yet(self):
        text = format_usage(dict(REPORT, calls=0, providers={}, last_provider=""), [dict(GROQ, limits=None)])
        self.assertIn("ainda sem dados de limite", text)
        self.assertIn("<b>Reserva:</b> nenhuma ligada", text)
        self.assertNotIn("Última resposta", text)

    def test_no_cap_configured(self):
        text = format_usage(dict(REPORT, cap=None), [GROQ])
        self.assertNotIn("Teto diário", text)


if __name__ == "__main__":
    unittest.main()
