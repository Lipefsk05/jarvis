import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from jarvis.assistant import BLOCKED_MESSAGE, FAILED_MESSAGE, Assistant, split_joke
from jarvis.budget import Budget
from jarvis.conversation import History
from jarvis.humor import HumorGate
from jarvis.talker.base import Reply, TalkerError, ToolCall

NOW = datetime(2026, 10, 8, 14, 30)
TEMPLATE = "SYS humor={{humor_permitido}} estado={{estado_atual}}"


class FakeTalker:
    def __init__(self, replies=None, error=None):
        self.calls = []
        self._replies = list(replies or [Reply("ok", 1000, 100)])
        self._error = error

    def reply(self, system, messages, tools=None, private=False):
        self.calls.append((system, messages))
        self.private_seen = private
        self.tools_seen = tools
        if self._error:
            raise self._error
        return self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]


class AssistantTest(unittest.TestCase):
    def make(self, tmp, talker, cap=10.0, estado=None):
        budget = Budget(Path(tmp) / "usage.json", cap, 1.0, 5.0, clock=lambda: NOW)
        return Assistant(
            talker=talker, budget=budget, gate=HumorGate(min_gap=2), history=History(),
            template=TEMPLATE, clock=lambda: NOW, estado_path=estado,
        ), budget

    def test_happy_path_records_history_and_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker([Reply("Boa tarde, senhor.", 1_000_000, 0)])
            a, budget = self.make(tmp, talker)
            r = a.respond(1, "oi")
            self.assertEqual(r.text, "Boa tarde, senhor.")
            self.assertFalse(r.humor_offered)  # no joke mark -> no button
            self.assertAlmostEqual(budget.spent_today(), 1.0)
            system, messages = talker.calls[0]
            self.assertIn("humor=SIM", system)
            self.assertEqual(messages, [{"role": "user", "content": "oi"}])

    def test_provider_and_explicit_cost_come_from_the_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker([Reply("oi, senhor", 5_000_000, 0, provider="groq", cost_usd=0.0)])
            a, budget = self.make(tmp, talker)
            r = a.respond(1, "oi")
            self.assertEqual(r.provider, "groq")
            self.assertEqual(budget.spent_today(), 0.0)  # default price would have said US$ 5

    def test_joke_tag_is_unwrapped_and_flags_the_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker([Reply("Boa tarde, senhor. [[humor: Pontualidade rara, para variar.]]", 10, 5)])
            a, _ = self.make(tmp, talker)
            r = a.respond(1, "oi")
            self.assertEqual(r.text, "Boa tarde, senhor. Pontualidade rara, para variar.")
            self.assertTrue(r.humor_offered)
            a.respond(1, "e aí")
            history = talker.calls[1][1]
            self.assertEqual(history[1], {"role": "assistant", "content": "Boa tarde, senhor. Pontualidade rara, para variar."})

    def test_bare_humor_tag_is_not_a_joke(self):
        # Seen live with gpt-oss-120b: "[[humor]]" appended to plain greetings and explanations.
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker([Reply("Boa tarde, senhor. [[humor]]", 10, 5), Reply("ok", 10, 5)])
            a, _ = self.make(tmp, talker)
            r = a.respond(1, "oi")
            self.assertEqual(r.text, "Boa tarde, senhor.")
            self.assertFalse(r.humor_offered)
            a.respond(1, "e aí")
            self.assertIn("humor=SIM", talker.calls[1][0])  # the slot was not consumed

    def test_split_joke_cases(self):
        cases = [
            ("Boa, senhor. [humor: sempre pontual, esse senhor]", "Boa, senhor. sempre pontual, esse senhor", True),
            ("Boa, senhor. [[Humor]]", "Boa, senhor.", False),
            ("Qual foi o erro, senhor?]]", "Qual foi o erro, senhor?", False),
            ("Veja a nota [1] acima.", "Veja a nota [1] acima.", False),
            ("Veja [[humor: sim]] isso.", "Veja isso.", False),
            ("A [[humor: piada com várias palavras]] fica no meio.", "A piada com várias palavras fica no meio.", True),
            ("Boa tarde, senhor.[[humor: Prefiro a compostura de um mordomo.]]", "Boa tarde, senhor. Prefiro a compostura de um mordomo.", True),
        ]
        for raw, expected, joked in cases:
            self.assertEqual(split_joke(raw), (expected, joked), raw)

    def test_cooldown_starts_only_after_a_real_joke(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker([Reply("sem graça", 10, 5),
                                 Reply("ok [[humor: uma observação seca e espirituosa]]", 10, 5), Reply("x", 10, 5)])
            a, _ = self.make(tmp, talker)
            a.respond(1, "oi")        # permitted, no joke made -> slot kept
            a.respond(1, "e aí")      # permitted again, joke made
            a.respond(1, "certo")     # now in cooldown
            self.assertIn("humor=SIM", talker.calls[0][0])
            self.assertIn("humor=SIM", talker.calls[1][0])
            self.assertIn("humor=NÃO", talker.calls[2][0])

    def test_reply_that_is_only_the_mark_counts_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker([Reply("[[humor]]", 10, 5)])
            a, _ = self.make(tmp, talker)
            self.assertEqual(a.respond(1, "oi").text, FAILED_MESSAGE)
            self.assertEqual(a._history.messages(1), [])

    def test_task_context_is_injected_only_when_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "vault"
            (root / "tarefas" / "pessoal").mkdir(parents=True)
            (root / "tarefas" / "pessoal" / "carreira.md").write_text("## Vaga\n- [ ] **Candidatura CLT**\n", encoding="utf-8")
            talker = FakeTalker()
            a, _ = self.make(tmp, talker)
            a._mind_dir = root
            a._template = "SYS tarefas={{tarefas_mind}}"
            a.respond(1, "oi")
            self.assertIn("nenhum dado de tarefas", talker.calls[0][0])
            a.respond(1, "quais são minhas tarefas de carreira?")
            self.assertIn("Candidatura CLT", talker.calls[1][0])

    def test_task_titles_are_sent_as_private_and_a_failure_points_to_the_command(self):
        from jarvis.assistant import TASKS_UNAVAILABLE_MESSAGE

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "vault"
            (root / "tarefas" / "pessoal").mkdir(parents=True)
            (root / "tarefas" / "pessoal" / "carreira.md").write_text("## Vaga\n- [ ] **Candidatura CLT**\n", encoding="utf-8")
            talker = FakeTalker()
            a, _ = self.make(tmp, talker)
            a._mind_dir = root
            a.respond(1, "oi")
            self.assertFalse(talker.private_seen)
            a.respond(1, "quais são minhas tarefas de carreira?")
            self.assertTrue(talker.private_seen)
            failing, _ = self.make(tmp, FakeTalker(error=TalkerError("x")))
            failing._mind_dir = root
            self.assertEqual(failing.respond(1, "quais são minhas tarefas de carreira?").text, TASKS_UNAVAILABLE_MESSAGE)

    def test_greeting_gets_a_variety_hint_and_other_messages_an_explicit_no_greeting_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker()
            a, _ = self.make(tmp, talker)
            a._template = "SYS dica={{dica_de_estilo}}"
            a.respond(1, "bom dia")
            a.respond(1, "me explica o que é DNS")
            self.assertIn("Cumprimente", talker.calls[0][0])
            self.assertIn("não é um cumprimento", talker.calls[1][0])

    def test_a_tool_call_becomes_an_action_and_the_model_text_is_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            call = ToolCall("anotar", {"texto": "  levar o carro na oficina sexta  "})
            talker = FakeTalker([Reply("Pode deixar, senhor!", 1000, 20, tool_call=call)])
            a, budget = self.make(tmp, talker)
            r = a.respond(1, "não esquece que preciso levar o carro na oficina sexta")
            self.assertEqual((r.text, r.action.name, r.action.texto), ("", "anotar", "levar o carro na oficina sexta"))
            self.assertGreater(budget.summary().count("1 chamadas"), 0)
            self.assertIsNotNone(talker.tools_seen)  # the tools were offered to the model
            a.remember(1, "Anotado, senhor: “levar o carro na oficina sexta”.")
            a.respond(1, "valeu")
            roles = [m["role"] for m in talker.calls[1][1]]
            self.assertEqual(roles, ["user", "assistant", "user"])  # no model text was stored for the action turn

    def test_the_answering_provider_is_recorded_in_the_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker([Reply("oi", 100, 10, provider="gemini", cost_usd=0.0)])
            a, budget = self.make(tmp, talker)
            a.respond(1, "e aí")
            self.assertEqual(budget.report()["providers"]["gemini"]["calls"], 1)
            self.assertEqual(a.provider_info(), [])  # a plain fake talker does not describe itself

    def test_unknown_or_malformed_tool_calls_are_ignored(self):
        for call in (ToolCall("apagar_tudo", {}), ToolCall("anotar", {}), ToolCall("anotar", {"texto": 42})):
            with tempfile.TemporaryDirectory() as tmp:
                talker = FakeTalker([Reply("Entendido.", 10, 5, tool_call=call)])
                a, _ = self.make(tmp, talker)
                r = a.respond(1, "faz algo")
                self.assertIsNone(r.action, call)
                self.assertEqual(r.text, "Entendido.")

    def test_blocked_when_over_budget_without_calling_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker()
            a, budget = self.make(tmp, talker, cap=0.001)
            budget.add(1_000_000, 0)
            r = a.respond(1, "oi")
            self.assertTrue(r.blocked)
            self.assertEqual(r.text, BLOCKED_MESSAGE)
            self.assertEqual(talker.calls, [])

    def test_provider_failure_rolls_back_history_and_hides_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker(error=TalkerError("RateLimitError"))
            a, budget = self.make(tmp, talker)
            r = a.respond(1, "oi")
            self.assertEqual(r.text, FAILED_MESSAGE)
            self.assertEqual(budget.spent_today(), 0.0)
            a._talker = FakeTalker()
            a.respond(1, "de novo")
            self.assertEqual(a._talker.calls[0][1], [{"role": "user", "content": "de novo"}])

    def test_warns_when_crossing_eighty_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            talker = FakeTalker([Reply("x", 900_000, 0)])
            a, _ = self.make(tmp, talker, cap=1.0)
            self.assertTrue(a.respond(1, "oi").warn_budget)
            self.assertFalse(a.respond(1, "oi").warn_budget)

    def test_estado_atual_is_injected(self):
        with tempfile.TemporaryDirectory() as tmp:
            estado = Path(tmp) / "estado.md"
            estado.write_text("projeto Jarvis em andamento", encoding="utf-8")
            talker = FakeTalker()
            a, _ = self.make(tmp, talker, estado=estado)
            a.respond(1, "oi")
            self.assertIn("projeto Jarvis em andamento", talker.calls[0][0])


if __name__ == "__main__":
    unittest.main()


class ReminderGuardTest(unittest.TestCase):
    def make(self, tmp, talker):
        budget = Budget(Path(tmp) / "usage.json", 10.0, 1.0, 5.0, clock=lambda: NOW)
        return Assistant(
            talker=talker, budget=budget, gate=HumorGate(min_gap=2), history=History(),
            template=TEMPLATE, clock=lambda: NOW,
        )

    def call(self):
        return Reply("", 100, 10, tool_call=ToolCall("criar_lembrete", {"texto": "dentista", "quando": "amanhã às 14h"}))

    def test_a_remark_is_not_a_reminder_request_even_if_the_model_calls_the_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.make(tmp, FakeTalker([self.call()]))
            r = a.respond(1, "tenho dentista amanhã às 14h")
            self.assertIsNone(r.action)
            self.assertIn("Quer que eu o avise", r.text)
            self.assertIn("amanhã às 14h", r.text)

    def test_explicit_requests_go_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            for text in ("me lembra do dentista amanhã às 14h", "me avisa amanhã às 14h do dentista",
                         "não me deixa esquecer do dentista amanhã às 14h", "preciso ser lembrado do dentista amanhã às 14h"):
                a = self.make(tmp, FakeTalker([self.call()]))
                self.assertEqual(a.respond(1, text).action.name, "criar_lembrete", text)

    def test_a_yes_after_the_offer_goes_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.make(tmp, FakeTalker([self.call(), self.call()]))
            self.assertIsNone(a.respond(1, "tenho dentista amanhã às 14h").action)
            self.assertEqual(a.respond(1, "sim, pode").action.name, "criar_lembrete")

    def test_a_yes_without_any_offer_does_not_create_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.make(tmp, FakeTalker([Reply("Boa tarde, senhor.", 10, 5), self.call()]))
            a.respond(1, "bom dia")
            self.assertIsNone(a.respond(1, "sim, pode").action)


class ReminderGuardAfterConfirmationsTest(ReminderGuardTest):
    """History drops a leading assistant message, so each case starts from a conversation in progress."""

    def started(self, tmp, then_assistant_said):
        a = self.make(tmp, FakeTalker([Reply("Boa tarde, senhor.", 10, 5), self.call()]))
        a.respond(1, "bom dia")
        a.remember(1, then_assistant_said)
        return a

    def test_a_cancellation_confirmation_is_not_an_offer(self):
        # Real case (2026-10-09): right after "Lembrete 8 cancelado", a bare remark created a reminder.
        with tempfile.TemporaryDirectory() as tmp:
            a = self.started(tmp, "Lembrete 8 cancelado, senhor: dentista.")
            self.assertIsNone(a.respond(1, "tenho dentista amanhã às 14h").action)

    def test_other_confirmations_and_listings_are_not_offers_either(self):
        for previous in ("Marcado, senhor (lembrete 3): amanhã às 09:00, pagar o aluguel.",
                         "(Mostrei os lembretes pendentes.)", "Lembretes pendentes, senhor (2): ..."):
            with tempfile.TemporaryDirectory() as tmp:
                a = self.started(tmp, previous)
                self.assertIsNone(a.respond(1, "tenho dentista amanhã às 14h").action, previous)

    def test_a_question_offering_a_reminder_still_lets_a_yes_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.started(tmp, "Deseja que eu crie um lembrete para o dentista, senhor?")
            self.assertEqual(a.respond(1, "sim").action.name, "criar_lembrete")


class OfferConfirmationTest(ReminderGuardTest):
    def blocked(self, tmp, extra=None):
        talker = FakeTalker([self.call(), *(extra or [])])
        a = self.make(tmp, talker)
        a.respond(1, "tenho dentista amanhã às 14h")  # blocked: becomes an offer
        return a, talker

    def test_a_plain_yes_creates_exactly_what_was_offered_without_the_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            for yes in ("sim", "sim, pode", "Me lembre sim", "pode sim", "claro", "isso mesmo", "me lembra sim por favor"):
                a, talker = self.blocked(tmp)
                action = a.confirm_offer(1, yes)
                self.assertEqual((action.name, action.texto, action.quando), ("criar_lembrete", "dentista", "amanhã às 14h"), yes)
                self.assertEqual(len(talker.calls), 1, yes)  # the model was not asked again

    def test_an_offer_can_only_be_accepted_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, _ = self.blocked(tmp)
            self.assertIsNotNone(a.confirm_offer(1, "sim"))
            self.assertIsNone(a.confirm_offer(1, "sim"))

    def test_anything_else_closes_the_offer(self):
        with tempfile.TemporaryDirectory() as tmp:
            for other in ("não", "deixa pra lá", "me lembra amanhã às 9 de pagar a luz", "e o clima hoje?"):
                a, _ = self.blocked(tmp)
                self.assertIsNone(a.confirm_offer(1, other), other)
                self.assertIsNone(a.confirm_offer(1, "sim"), other)  # and a later yes finds nothing

    def test_an_old_offer_expires(self):
        with tempfile.TemporaryDirectory() as tmp:
            from datetime import timedelta as td
            now = [NOW]
            budget = Budget(Path(tmp) / "usage.json", 10.0, 1.0, 5.0, clock=lambda: NOW)
            a = Assistant(talker=FakeTalker([self.call()]), budget=budget, gate=HumorGate(min_gap=2),
                          history=History(), template=TEMPLATE, clock=lambda: now[0])
            a.respond(1, "tenho dentista amanhã às 14h")
            now[0] = NOW + td(minutes=11)
            self.assertIsNone(a.confirm_offer(1, "sim"))

    def test_a_yes_with_no_offer_does_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(self.make(tmp, FakeTalker()).confirm_offer(1, "sim"))
