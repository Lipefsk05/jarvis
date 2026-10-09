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


class ReminderToolsTest(unittest.TestCase):
    def test_create_reminder_valid_and_with_lead(self):
        self.assertEqual(
            parse_action(ToolCall("criar_lembrete", {"texto": " pg jovem ", "quando": "hoje às 19", "antecedencia_minutos": 10})),
            Action("criar_lembrete", texto="pg jovem", quando="hoje às 19", antecedencia=10),
        )
        self.assertEqual(parse_action(ToolCall("criar_lembrete", {"texto": "x", "quando": "amanhã", "antecedencia_minutos": "30"})).antecedencia, 30)
        self.assertEqual(parse_action(ToolCall("criar_lembrete", {"texto": "x", "quando": "amanhã", "antecedencia_minutos": 15.0})).antecedencia, 15)
        self.assertEqual(parse_action(ToolCall("criar_lembrete", {"texto": "x", "quando": "amanhã", "antecedencia_minutos": None})).antecedencia, 0)

    def test_create_reminder_rejects_missing_or_absurd_arguments(self):
        for args in ({"texto": "x"}, {"quando": "amanhã"}, {"texto": " ", "quando": "amanhã"},
                     {"texto": "x", "quando": "amanhã", "antecedencia_minutos": -5},
                     {"texto": "x", "quando": "amanhã", "antecedencia_minutos": 99999},
                     {"texto": "x", "quando": "amanhã", "antecedencia_minutos": "dez"},
                     {"texto": "x", "quando": "amanhã", "antecedencia_minutos": True},
                     {"texto": ["x"], "quando": "amanhã"}):
            self.assertIsNone(parse_action(ToolCall("criar_lembrete", args)), args)

    def test_cancel_reminder_needs_a_number_or_a_search(self):
        self.assertEqual(parse_action(ToolCall("cancelar_lembrete", {"numero": 3})), Action("cancelar_lembrete", numero=3))
        self.assertEqual(parse_action(ToolCall("cancelar_lembrete", {"busca": " aluguel "})), Action("cancelar_lembrete", busca="aluguel"))
        for args in ({}, {"numero": 0}, {"numero": -1}, {"numero": "abc"}, {"busca": "  "}):
            self.assertIsNone(parse_action(ToolCall("cancelar_lembrete", args)), args)
        self.assertEqual(parse_action(ToolCall("listar_lembretes", {})), Action("listar_lembretes"))


class OptionalFieldsAcceptNullTest(unittest.TestCase):
    def test_optional_fields_declare_null_because_models_send_it(self):
        # Groq rejects `null` for a field declared only as integer/string (HTTP 400 tool_use_failed).
        for name, field in (("criar_lembrete", "antecedencia_minutos"), ("cancelar_lembrete", "numero"), ("cancelar_lembrete", "busca")):
            spec = next(t for t in TOOLS if t["function"]["name"] == name)["function"]["parameters"]
            self.assertIn("null", spec["properties"][field]["type"], f"{name}.{field}")
            self.assertNotIn(field, spec["required"])

    def test_null_arguments_are_treated_as_absent(self):
        self.assertEqual(
            parse_action(ToolCall("criar_lembrete", {"texto": "x", "quando": "amanhã", "antecedencia_minutos": None})).antecedencia, 0)
        self.assertEqual(
            parse_action(ToolCall("cancelar_lembrete", {"numero": None, "busca": "aluguel"})), Action("cancelar_lembrete", busca="aluguel"))
        self.assertEqual(
            parse_action(ToolCall("cancelar_lembrete", {"numero": 3, "busca": None})), Action("cancelar_lembrete", numero=3))
