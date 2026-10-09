import re
import unittest

from jarvis.commands import asks_capabilities
from jarvis.config import REPO_ROOT
from jarvis.help import COMMANDS, NOT_YET, format_help, menu
from jarvis.persona import load_template


class HelpTextTest(unittest.TestCase):
    def test_lists_every_command_with_its_description(self):
        text = format_help()
        for c in COMMANDS:
            self.assertIn(f"/{c.name}", text)
        self.assertIn("/anota &lt;texto&gt;", text)   # arguments are escaped for HTML
        self.assertIn("/tarefas [área]", text)
        self.assertIn(NOT_YET, text)

    def test_menu_entries_are_valid_for_telegram(self):
        for name, description in menu():
            self.assertRegex(name, r"^[a-z0-9_]{1,32}$")
            self.assertTrue(1 <= len(description) <= 256)
        self.assertEqual([n for n, _ in menu()], [c.name for c in COMMANDS])

    def test_persona_knows_every_real_command(self):
        template = load_template(REPO_ROOT / "persona" / "jarvis.md")
        for c in COMMANDS:
            self.assertIn(f"/{c.name}", template)

    def test_fits_in_one_telegram_message(self):
        self.assertLess(len(format_help()), 3900)


class AsksCapabilitiesTest(unittest.TestCase):
    def test_capability_questions(self):
        for text in ("oque voce pode fazer?", "o que você pode fazer", "oq vc pode fazer?", "como você pode me ajudar?",
                     "Em que você pode me ajudar atualmente?", "quais são suas funções?", "quais os seus comandos",
                     "pra que você serve", "como eu uso você?", "como usar isso", "me mostra os comandos", "ajuda", "help", "comandos", "menu",
                     "Kkkkkk boa, mas eai oq vc pode fazer?"):
            self.assertTrue(asks_capabilities(text), text)

    def test_other_messages_are_not_capability_questions(self):
        for text in ("preciso de ajuda com o deploy de ontem", "o que você acha do dindin?", "me explica o que é um webhook",
                     "o que eu posso fazer hoje?", "quais tarefas eu tenho?", "oi",
                     "o que você pode fazer com esse erro de deploy que apareceu ontem na produção do app"):
            self.assertFalse(asks_capabilities(text), text)


if __name__ == "__main__":
    unittest.main()
