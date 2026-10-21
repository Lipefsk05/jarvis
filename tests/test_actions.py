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


class LiveQuestionTest(unittest.TestCase):
    def test_a_question_about_live_public_data_is_a_request_for_the_internet(self):
        from jarvis.commands import has_intent, is_live_question
        for said in ("Qual a cotação do dólar atual?", "quanto está o bitcoin", "Quem ganhou o jogo ontem?",
                     "como está o clima em Recife agora?", "quanto custa um iPhone 16?", "o que aconteceu hoje no mundo?",
                     "Jarvis, qual o preço da gasolina?"):
            self.assertTrue(is_live_question(said), said)
            self.assertTrue(has_intent("delegar_trabalho", said), said)

    def test_questions_about_his_own_things_or_general_knowledge_are_not(self):
        from jarvis.commands import has_intent, is_live_question
        for said in ("Como está meu dia hoje?", "o que tenho na agenda amanhã?", "quais minhas tarefas pendentes?",
                     "Qual a capital da Austrália?", "me explica o que é DNS", "o dólar subiu", "preciso pagar o aluguel agora",
                     "no Mind, qual o preço da proposta do Pedro?"):
            self.assertFalse(is_live_question(said), said)
        self.assertFalse(has_intent("delegar_trabalho", "Qual a capital da Austrália?"))
        self.assertTrue(has_intent("delegar_trabalho", "pesquisa o preço do dólar"))  # the verbs still work


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


class ConcludeToolTest(unittest.TestCase):
    def test_the_done_tool_needs_a_task_and_has_no_sign_of_the_old_marks(self):
        from jarvis.actions import KNOWN, parse_action
        from jarvis.talker.base import ToolCall
        self.assertIn("concluir_tarefa", KNOWN)
        self.assertNotIn("avisar_marco", KNOWN)
        self.assertEqual(parse_action(ToolCall("concluir_tarefa", {"tarefa": " landing do dindin "})).tarefa, "landing do dindin")
        self.assertIsNone(parse_action(ToolCall("concluir_tarefa", {"tarefa": "  "})))

    def test_the_done_tool_needs_the_users_own_words(self):
        from jarvis.commands import has_intent
        for said in ("concluí a landing", "terminei o relatório", "fiz o cadastro", "finalizei tudo"):
            self.assertTrue(has_intent("concluir_tarefa", said), said)
        self.assertFalse(has_intent("concluir_tarefa", "amanhã eu vejo a landing"))


class AgendaActionsTest(unittest.TestCase):
    def test_valid_calls(self):
        from jarvis.commands import has_intent
        self.assertEqual(parse_action(ToolCall("consultar_agenda", {"quando": " amanhã "})), Action("consultar_agenda", quando="amanhã"))
        self.assertEqual(parse_action(ToolCall("consultar_agenda", {})), Action("consultar_agenda"))
        self.assertEqual(
            parse_action(ToolCall("criar_evento", {"titulo": "Dentista", "quando": "amanhã às 14", "duracao_minutos": None, "conta": None})),
            Action("criar_evento", texto="Dentista", quando="amanhã às 14"))
        self.assertEqual(
            parse_action(ToolCall("criar_evento", {"titulo": "Dentista", "quando": "amanhã às 14", "duracao_minutos": 90, "conta": "pessoal"})),
            Action("criar_evento", texto="Dentista", quando="amanhã às 14", duracao=90, conta="pessoal"))
        self.assertEqual(parse_action(ToolCall("mover_evento", {"busca": "dentista", "quando": "sexta"})), Action("mover_evento", busca="dentista", quando="sexta"))
        self.assertEqual(parse_action(ToolCall("cancelar_evento", {"busca": "dentista"})), Action("cancelar_evento", busca="dentista"))

    def test_malformed_calls_are_ignored(self):
        for call in (ToolCall("criar_evento", {"titulo": "x"}), ToolCall("criar_evento", {"titulo": "x", "quando": "amanhã", "duracao_minutos": 99999}),
                     ToolCall("criar_evento", {"titulo": "x", "quando": "amanhã", "duracao_minutos": "abc"}),
                     ToolCall("mover_evento", {"busca": "x"}), ToolCall("cancelar_evento", {}), ToolCall("cancelar_evento", {"busca": "  "})):
            self.assertIsNone(parse_action(call), call)

    def test_the_model_alone_cannot_change_the_agenda(self):
        from jarvis.commands import has_intent
        self.assertTrue(has_intent("criar_evento", "marca reunião amanhã às 15"))
        self.assertFalse(has_intent("criar_evento", "tenho dentista amanhã às 14"))
        self.assertTrue(has_intent("mover_evento", "muda o dentista pra segunda"))
        self.assertTrue(has_intent("mover_evento", "adia a reunião pra sexta"))
        self.assertFalse(has_intent("mover_evento", "o dentista é na segunda"))
        self.assertTrue(has_intent("cancelar_evento", "cancela a reunião de sexta"))
        self.assertFalse(has_intent("cancelar_evento", "a reunião de sexta foi boa"))
        self.assertTrue(has_intent("consultar_agenda", "o que tenho amanhã?"))
