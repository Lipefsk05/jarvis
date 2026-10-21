import tempfile
import unittest
from datetime import date
from pathlib import Path

from jarvis.board import HIGH, LOW, MEDIUM, UNRANKED, blocked, guess_needs, load_board, parse_task, split
from jarvis.plan import NOTEBOOK, PHONE

TODAY = date(2026, 10, 13)

BOARD = """\
# Tarefas — teste

## Casa

- [ ] 🔴 **Pagar o aluguel** — vence logo 📅 2026-10-15 ^vc-aluguel
- [ ] 🟡 Ligar pro banco sobre a fatura
- [ ] 🟢 Implementar a tela de login do app ⏱ 2h
- [ ] 💡 Ideia: app de looks
- [ ] Estudar canto 📱
- [ ] 🔴 📚 Inglês fluente ^vc-ingles
- [ ] 🔴 Subir o site 💻 ⛓ depende de ^vc-aluguel ^vc-site
- [ ] 🟡 Fechar contrato ⛓ depende do aceite
- [x] 🔴 Já feito
- [~] 🔴 Descartado
  - [ ] 🟡 Sub-item da casa

## Outra seção

- [ ] Tarefa sem marcador nenhum
"""


class BoardTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "tarefas" / "pessoal").mkdir(parents=True)
        (root / "tarefas" / "empresa").mkdir(parents=True)
        (root / "tarefas" / "pessoal" / "casa.md").write_text(BOARD, encoding="utf-8")
        (root / "tarefas" / "pessoal" / "pessoal.md").write_text("- [ ] 🔴 índice, não conta\n", encoding="utf-8")
        self.tasks = {t.title: t for t in load_board(root)}

    def test_only_open_bullets_and_no_index_files(self):
        self.assertEqual(len(self.tasks), 10)
        self.assertNotIn("Já feito", self.tasks)
        self.assertFalse(any("índice" in t for t in self.tasks))

    def test_priority_idea_due_and_id(self):
        rent = self.tasks["Pagar o aluguel"]
        self.assertEqual((rent.priority, rent.due, rent.task_id, rent.key), (HIGH, date(2026, 10, 15), "vc-aluguel", "^vc-aluguel"))
        self.assertEqual(self.tasks["Ligar pro banco sobre a fatura"].priority, MEDIUM)
        idea = self.tasks["Ideia: app de looks"]
        self.assertTrue(idea.idea)
        self.assertEqual(self.tasks["Tarefa sem marcador nenhum"].priority, UNRANKED)

    def test_dependencies(self):
        site = self.tasks["Subir o site"]
        self.assertEqual((site.depends, site.waits), (("vc-aluguel",), False))
        contract = self.tasks["Fechar contrato"]
        self.assertEqual((contract.depends, contract.waits), ((), True))
        self.assertTrue(blocked(site, {"vc-aluguel"}))
        self.assertFalse(blocked(site, set()))
        self.assertTrue(blocked(contract, set()))

    def test_the_waiting_mark_parks_the_task_and_says_for_whom(self):
        pedro = parse_task("empresa", "pedro", "", "", "🔴 **Aguardar o Pedro**; montar o contrato ⏳ aguardando o Pedro aprovar a proposta ^pd-contrato")
        self.assertTrue(pedro.waits)
        self.assertEqual(pedro.waiting_for, "o Pedro aprovar a proposta")
        self.assertEqual(pedro.task_id, "pd-contrato")
        self.assertNotIn("⏳", pedro.title)
        self.assertNotIn("proposta", pedro.title)
        bare = parse_task("empresa", "pedro", "", "", "🟡 Resposta do cliente ⏳")
        self.assertEqual((bare.waits, bare.waiting_for), (True, ""))
        self.assertFalse(parse_task("pessoal", "casa", "", "", "🟡 Trocar a lâmpada").waits)

    def test_where_and_how_long(self):
        self.assertEqual(self.tasks["Estudar canto"].needs, PHONE)
        self.assertTrue(self.tasks["Estudar canto"].needs_marked)
        self.assertEqual(self.tasks["Subir o site"].needs, NOTEBOOK)  # 💻 beats the words
        login = self.tasks["Implementar a tela de login do app"]
        self.assertEqual((login.needs, login.minutes, login.priority), (NOTEBOOK, 120, LOW))
        self.assertEqual(self.tasks["Tarefa sem marcador nenhum"].needs, NOTEBOOK)

    def test_subitems_keep_their_depth(self):
        self.assertEqual(self.tasks["Sub-item da casa"].depth, 1)
        self.assertEqual(self.tasks["Pagar o aluguel"].depth, 0)

    def test_buckets(self):
        buckets = split(list(self.tasks.values()), TODAY)
        titles = {k: [t.title for t in v] for k, v in buckets.items()}
        self.assertEqual(titles["prioridade"], ["Pagar o aluguel"])  # the site is blocked by it
        self.assertEqual(titles["ideias"], ["Ideia: app de looks"])
        self.assertEqual(titles["estudos"], ["Inglês fluente"])  # 🔴 but 📚: out of the daily plan
        self.assertIn("Subir o site", titles["lista"])
        self.assertIn("Fechar contrato", titles["lista"])

    def test_near_deadline_is_priority_even_without_red(self):
        buckets = split(list(self.tasks.values()), date(2026, 10, 9))
        self.assertIn("Pagar o aluguel", [t.title for t in buckets["prioridade"]])


class GuessTest(unittest.TestCase):
    def test_phone_words_and_computer_words(self):
        self.assertEqual(guess_needs("Ligar pro Bradesco sobre a fatura"), PHONE)
        self.assertEqual(guess_needs("Pagar Maceió — R$400"), PHONE)
        self.assertEqual(guess_needs("Estudar LGPD"), PHONE)
        self.assertEqual(guess_needs("Estudar como configurar o Firebase"), NOTEBOOK)
        self.assertEqual(guess_needs("Qualquer coisa sem pista"), NOTEBOOK)

    def test_only_the_lead_is_read(self):
        self.assertEqual(guess_needs("Revisar a tela " + "x " * 60 + "e ligar pra alguém"), NOTEBOOK)

    def test_whole_words_only(self):
        self.assertEqual(guess_needs("Controller do app nativo"), NOTEBOOK)


if __name__ == "__main__":
    unittest.main()
