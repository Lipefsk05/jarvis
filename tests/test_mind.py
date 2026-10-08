import tempfile
import unittest
from pathlib import Path

from jarvis.commands import task_query_words, wants_tasks
from jarvis.mind import load_pending, render_items, select, short_title, summary, tasks_context


def vault(tmp):
    root = Path(tmp)
    (root / "tarefas" / "pessoal").mkdir(parents=True)
    (root / "tarefas" / "empresa").mkdir(parents=True)
    (root / "tarefas" / "pessoal" / "pessoal.md").write_text("- [ ] index, must be ignored\n", encoding="utf-8")
    (root / "tarefas" / "pessoal" / "carreira.md").write_text(
        "# Carreira\n\n## Vaga de marketing\n"
        "- [ ] **Candidatura à vaga CLT** — em andamento, com [currículo](../x.md) dedicado\n"
        "- [x] **Já feito**\n"
        "## Portfólio\n"
        "- [ ] Reestruturar o `portfolio/` para suportar case studies\n",
        encoding="utf-8",
    )
    (root / "tarefas" / "pessoal" / "projetos-pessoais.md").write_text(
        "## Jarvis (evolução do Joee)\n- [ ] **Groq testado**: detalhes\n- [ ] Cadeia de provedores\n", encoding="utf-8"
    )
    (root / "tarefas" / "empresa" / "dindin.md").write_text("## Geral\n- [ ] **Publicar na Play Store**\n", encoding="utf-8")
    return root


class MindTasksTest(unittest.TestCase):
    def test_short_title(self):
        self.assertEqual(short_title("**Candidatura** — resto do texto longo"), "Candidatura")
        self.assertEqual(short_title("Ver [o guia](../a.md) com `código`"), "Ver o guia com código")
        long = "palavra " * 40
        title = short_title(long, 50)
        self.assertLessEqual(len(title), 51)
        self.assertTrue(title.endswith("…"))

    def test_load_pending_skips_done_and_index_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = load_pending(vault(tmp))
            titles = [t.title for t in tasks]
            self.assertNotIn("Já feito", titles)
            self.assertFalse(any("index" in t for t in titles))
            self.assertEqual(len(tasks), 5)
            first = tasks[0]  # personal tasks are read first
            self.assertEqual((first.group, first.area, first.section), ("pessoal", "carreira", "Vaga de marketing"))
            dindin = [t for t in tasks if t.area == "dindin"]
            self.assertEqual([(t.group, t.section, t.title) for t in dindin], [("empresa", "Geral", "Publicar na Play Store")])

    def test_summary_counts_per_area(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                summary(load_pending(vault(tmp))),
                "empresa/dindin: 1; pessoal/carreira: 2; pessoal/projetos-pessoais: 2",
            )

    def test_select_by_area_section_and_accent_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = load_pending(vault(tmp))
            self.assertEqual(len(select(tasks, ["carreira"])), 2)
            self.assertEqual(len(select(tasks, ["jarvis"])), 2)      # matches the ## heading
            self.assertEqual(len(select(tasks, ["evolucao"])), 2)    # accent-insensitive
            self.assertEqual(len(select(tasks, ["empresa"])), 1)     # matches the group
            self.assertEqual(select(tasks, ["nada"]), [])
            self.assertEqual(select(tasks, []), [])

    def test_render_items_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = render_items(load_pending(vault(tmp)), limit=2)
            self.assertIn("(+3 não mostradas)", text)

    def test_tasks_context_gives_counts_or_the_chosen_area(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = vault(tmp)
            self.assertIn("pessoal/carreira: 2", tasks_context(root, []))
            chosen = tasks_context(root, ["carreira"])
            self.assertIn("2 pendentes na área pedida", chosen)
            self.assertIn("Candidatura à vaga CLT", chosen)

    def test_missing_vault_is_empty_not_an_error(self):
        self.assertEqual(load_pending(Path("/nonexistent/vault")), [])


class TaskRequestTest(unittest.TestCase):
    def test_wants_tasks(self):
        for text in ("quais tarefas eu tenho?", "minhas pendências", "tarefas de carreira", "o que eu preciso pra fazer hoje", "to-do"):
            self.assertTrue(wants_tasks(text), text)
        for text in ("oi", "como está o tempo", "me explica o que é um container"):
            self.assertFalse(wants_tasks(text), text)

    def test_query_words(self):
        self.assertEqual(task_query_words("quais tarefas eu tenho?"), [])
        self.assertEqual(task_query_words("tarefas de carreira"), ["carreira"])
        self.assertEqual(task_query_words("e as pendências do Dindin?"), ["dindin"])


if __name__ == "__main__":
    unittest.main()
