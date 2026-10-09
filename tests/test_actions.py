import unittest

from jarvis.actions import KNOWN, MAX_AREA_CHARS, MAX_NOTE_CHARS, TOOLS, Action, parse_action
from jarvis.talker.base import ToolCall


class ToolSpecTest(unittest.TestCase):
    def test_every_tool_is_well_formed_and_named_once(self):
        names = [t["function"]["name"] for t in TOOLS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), KNOWN)
        for tool in TOOLS:
            fn = tool["function"]
            self.assertEqual(tool["type"], "function")
            self.assertTrue(fn["description"])
            self.assertEqual(fn["parameters"]["type"], "object")
            for required in fn["parameters"]["required"]:
                self.assertIn(required, fn["parameters"]["properties"])

    def test_the_note_tool_warns_against_casual_remarks(self):
        description = next(t for t in TOOLS if t["function"]["name"] == "anotar")["function"]["description"]
        self.assertIn("SOMENTE", description)


class ParseActionTest(unittest.TestCase):
    def test_valid_calls(self):
        self.assertEqual(parse_action(ToolCall("anotar", {"texto": " comprar pão "})), Action("anotar", texto="comprar pão"))
        self.assertEqual(parse_action(ToolCall("consultar_tarefas", {"area": " dindin "})), Action("consultar_tarefas", area="dindin"))
        self.assertEqual(parse_action(ToolCall("consultar_tarefas", {})), Action("consultar_tarefas"))
        for name in ("ver_gasto", "mostrar_ajuda", "limpar_conversa"):
            self.assertEqual(parse_action(ToolCall(name, {})), Action(name))

    def test_rejects_unknown_empty_or_wrongly_typed(self):
        for call in (None, ToolCall("rm_rf", {}), ToolCall("anotar", {}), ToolCall("anotar", {"texto": "   "}),
                     ToolCall("anotar", {"texto": ["x"]}), ToolCall("anotar", "not a dict")):
            self.assertIsNone(parse_action(call), call)

    def test_arguments_are_length_capped(self):
        self.assertEqual(len(parse_action(ToolCall("anotar", {"texto": "x" * 10_000})).texto), MAX_NOTE_CHARS)
        self.assertEqual(len(parse_action(ToolCall("consultar_tarefas", {"area": "y" * 500})).area), MAX_AREA_CHARS)


if __name__ == "__main__":
    unittest.main()
