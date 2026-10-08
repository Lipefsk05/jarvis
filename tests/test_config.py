import tempfile
import unittest
from pathlib import Path

from jarvis.config import Settings, parse_env_file


class ParseEnvFileTest(unittest.TestCase):
    def test_parses_values_comments_and_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text('# c\n\nA=1\nB="two words"\nC=\nD=x=y\n', encoding="utf-8")
            self.assertEqual(
                parse_env_file(path), {"A": "1", "B": "two words", "C": "", "D": "x=y"}
            )

    def test_missing_file_is_empty(self):
        self.assertEqual(parse_env_file(Path("/nonexistent/.env")), {})


class SettingsTest(unittest.TestCase):
    def load(self, environ):
        return Settings.load(env_path=Path("/nonexistent/.env"), environ=environ)

    def test_defaults_and_ids(self):
        s = self.load({"TELEGRAM_ALLOWED_USER_IDS": "10, 20,,"})
        self.assertEqual(s.provider, "anthropic")
        self.assertEqual(s.model, "claude-haiku-5-5")
        self.assertEqual(s.allowed_ids, frozenset({10, 20}))
        self.assertEqual((s.price_in, s.price_out), (1.0, 5.0))

    def test_gemini_is_free_by_default(self):
        s = self.load({"JARVIS_TALKER_PROVIDER": "gemini"})
        self.assertEqual((s.price_in, s.price_out), (0.0, 0.0))
        self.assertEqual(s.model, "gemini-2.5-flash")
        self.assertEqual(s.fallback_models, ("gemini-3.5-flash",))

    def test_groq_defaults_and_key_check(self):
        s = self.load({"JARVIS_TALKER_PROVIDER": "groq"})
        self.assertEqual(s.model, "openai/gpt-oss-120b")
        self.assertEqual(s.fallback_models, ("openai/gpt-oss-20b",))
        self.assertEqual((s.price_in, s.price_out), (0.0, 0.0))
        self.assertTrue(any("GROQ_API_KEY" in p for p in s.problems()))
        ok = self.load({"JARVIS_TALKER_PROVIDER": "groq", "GROQ_API_KEY": "k"})
        self.assertFalse(any("GROQ" in p for p in ok.problems()))

    def test_mind_dir_and_inbox_default(self):
        s = self.load({"JARVIS_MIND_DIR": "/tmp/somevault"})
        self.assertEqual(str(s.mind_dir), "/tmp/somevault")
        self.assertEqual(str(s.inbox_dir), "/tmp/somevault/inbox/jarvis")
        s = self.load({"JARVIS_MIND_DIR": "/tmp/somevault", "JARVIS_INBOX_DIR": "/tmp/elsewhere"})
        self.assertEqual(str(s.inbox_dir), "/tmp/elsewhere")

    def test_fallback_providers_parsing_and_validation(self):
        self.assertEqual(self.load({}).fallback_providers, ())
        s = self.load({"JARVIS_TALKER_PROVIDER": "groq", "JARVIS_TALKER_FALLBACK_PROVIDERS": " Gemini , groq, gemini,anthropic "})
        self.assertEqual(s.fallback_providers, ("gemini", "anthropic"))  # lowercased, deduped, no primary
        bad = self.load({"JARVIS_TALKER_FALLBACK_PROVIDERS": "gemini,nope"})
        self.assertTrue(any("nope" in p for p in bad.problems()))

    def test_key_for(self):
        s = self.load({"GROQ_API_KEY": "g", "GEMINI_API_KEY": "m"})
        self.assertEqual((s.key_for("groq"), s.key_for("gemini"), s.key_for("anthropic"), s.key_for("x")), ("g", "m", "", ""))

    def test_fallback_models_override_and_anthropic_default(self):
        self.assertEqual(self.load({}).fallback_models, ())
        s = self.load({"JARVIS_TALKER_FALLBACK_MODELS": " a , b ,"})
        self.assertEqual(s.fallback_models, ("a", "b"))

    def test_price_override_and_comma_decimal(self):
        s = self.load({"JARVIS_PRICE_IN_PER_MTOK": "0,5", "JARVIS_DAILY_BUDGET_USD": "1,5"})
        self.assertEqual(s.price_in, 0.5)
        self.assertEqual(s.daily_budget_usd, 1.5)

    def test_environment_overrides_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("JARVIS_TALKER_PROVIDER=gemini\n", encoding="utf-8")
            s = Settings.load(env_path=path, environ={"JARVIS_TALKER_PROVIDER": "anthropic"})
            self.assertEqual(s.provider, "anthropic")

    def test_problems_lists_everything_missing(self):
        problems = self.load({}).problems()
        self.assertTrue(any("TELEGRAM_BOT_TOKEN" in p for p in problems))
        self.assertTrue(any("ALLOWED_USER_IDS" in p for p in problems))
        self.assertTrue(any("ANTHROPIC_API_KEY" in p for p in problems))
        self.assertTrue(any("DAILY_BUDGET" in p for p in problems))

    def test_no_problems_when_complete(self):
        s = self.load({
            "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_ALLOWED_USER_IDS": "1",
            "JARVIS_TALKER_PROVIDER": "gemini", "GEMINI_API_KEY": "k",
            "JARVIS_DAILY_BUDGET_USD": "1",
        })
        self.assertEqual(s.problems(), [])

    def test_unknown_provider_is_a_problem(self):
        self.assertTrue(any("PROVIDER" in p for p in self.load({"JARVIS_TALKER_PROVIDER": "x"}).problems()))


if __name__ == "__main__":
    unittest.main()
