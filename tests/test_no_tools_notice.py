import unittest

from jarvis.help import COMMANDS
from jarvis.talker.base import NO_TOOLS_NOTICE, without_tools


class NoToolsNoticeTest(unittest.TestCase):
    def test_only_added_when_tools_were_offered(self):
        self.assertEqual(without_tools("sistema", None), "sistema")
        self.assertEqual(without_tools("sistema", []), "sistema")
        self.assertEqual(without_tools("sistema", [{"type": "function"}]), "sistema" + NO_TOOLS_NOTICE)

    def test_points_to_commands_that_exist_and_forbids_pretending(self):
        real = {f"/{c.name}" for c in COMMANDS}
        for command in ("/anota", "/lembra", "/lembretes", "/cancela", "/tarefas", "/uso"):
            self.assertIn(command, NO_TOOLS_NOTICE)
            self.assertIn(command, real)
        self.assertIn("Nunca", NO_TOOLS_NOTICE)
