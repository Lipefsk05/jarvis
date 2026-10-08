import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from jarvis.config import REPO_ROOT
from jarvis.conversation import History
from jarvis.inbox import write_note
from jarvis.persona import format_now, load_template, render

NOW = datetime(2026, 10, 8, 14, 30)  # a Thursday


class PersonaTest(unittest.TestCase):
    def test_load_template_skips_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.md"
            path.write_text("# T\nnotes\n\n---\n\nBody here\n", encoding="utf-8")
            self.assertEqual(load_template(path), "Body here")

    def test_format_now_uses_portuguese_weekday(self):
        self.assertEqual(format_now(NOW), "quinta-feira, 08/10/2026 14:30")

    def test_render_fills_all_placeholders(self):
        template = "{{data_hora}}|{{humor_permitido}}|{{estado_atual}}|{{resumo_conversa}}"
        out = render(template, humor_allowed=False, now=NOW)
        self.assertNotIn("{{", out)
        self.assertIn("NÃO", out)
        self.assertIn("nenhum estado", out)
        on = render(template, humor_allowed=True, now=NOW, estado_atual="projeto X")
        self.assertIn("SIM", on)
        self.assertIn("projeto X", on)

    def test_real_persona_file_renders_without_leftovers(self):
        template = load_template(REPO_ROOT / "persona" / "jarvis.md")
        out = render(template, humor_allowed=True, now=NOW)
        self.assertNotIn("{{", out)
        self.assertIn("senhor", out)


class HistoryTest(unittest.TestCase):
    def test_trims_and_starts_with_user(self):
        h = History(max_messages=3)
        for i in range(3):
            h.add(1, "user", f"u{i}")
            h.add(1, "assistant", f"a{i}")
        msgs = h.messages(1)
        self.assertLessEqual(len(msgs), 3)
        self.assertEqual(msgs[0]["role"], "user")

    def test_drop_last_and_clear(self):
        h = History()
        h.add(1, "user", "oi")
        h.drop_last(1)
        self.assertEqual(h.messages(1), [])
        h.add(1, "user", "oi")
        h.clear(1)
        self.assertEqual(h.messages(1), [])

    def test_messages_returns_copies(self):
        h = History()
        h.add(1, "user", "oi")
        h.messages(1)[0]["content"] = "mutated"
        self.assertEqual(h.messages(1)[0]["content"], "oi")


class InboxTest(unittest.TestCase):
    def test_writes_note_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "inbox" / "jarvis"
            first = write_note(inbox, "comprar café", NOW)
            second = write_note(inbox, "outra", NOW)
            self.assertNotEqual(first, second)
            text = first.read_text(encoding="utf-8")
            self.assertIn("origem: telegram", text)
            self.assertIn("comprar café", text)
            self.assertTrue(text.startswith("---\n"))


if __name__ == "__main__":
    unittest.main()


class NoInventionTest(unittest.TestCase):
    def test_missing_tasks_context_tells_the_model_not_to_invent(self):
        out = render("{{tarefas_mind}}", humor_allowed=False, now=NOW)
        self.assertIn("não invente", out)

    def test_real_persona_forbids_inventing_user_data(self):
        template = load_template(REPO_ROOT / "persona" / "jarvis.md")
        self.assertIn("Nunca invente", template)

    def test_real_persona_lists_the_only_existing_commands(self):
        template = load_template(REPO_ROOT / "persona" / "jarvis.md")
        self.assertIn("únicos comandos que existem", template)
        for command in ("/anota", "/tarefas", "/uso", "/esquece"):
            self.assertIn(command, template)
