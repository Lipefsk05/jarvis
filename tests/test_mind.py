import tempfile
import unittest
from pathlib import Path

from jarvis.commands import task_query_words, wants_tasks
from jarvis.mind import load_pending, render_items, resolve_query, select, short_title, suggest, summary, tasks_context


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


class TypoToleranceTest(unittest.TestCase):
    def tasks(self, tmp):
        return load_pending(vault(tmp))

    def test_suggests_the_closest_name_for_real_typos(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = self.tasks(tmp)
            self.assertEqual(suggest(tasks, "dindim"), "dindin")
            self.assertEqual(suggest(tasks, "carrera"), "carreira")   # missing letter
            self.assertEqual(suggest(tasks, "dinidn"), "dindin")      # transposed letters
            self.assertEqual(suggest(tasks, "jarvs"), "jarvis")       # from a section heading

    def test_ordinary_words_are_not_forced_onto_a_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = self.tasks(tmp)
            for word in ("hoje", "semana", "fazer", "xyzzy"):
                self.assertIsNone(suggest(tasks, word), word)

    def test_resolve_query_keeps_good_words_and_fixes_bad_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = self.tasks(tmp)
            self.assertEqual(resolve_query(tasks, ["carreira"]), (["carreira"], []))
            words, fixes = resolve_query(tasks, ["dindn", "marketing"])
            self.assertEqual(words, ["dindin", "marketing"])
            self.assertEqual(fixes, [("dindn", "dindin")])
            self.assertIn("dindin", {t.area for t in select(tasks, words)})

    def test_unknown_word_stays_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(resolve_query(self.tasks(tmp), ["banana"]), (["banana"], []))


class TaskRequestTest(unittest.TestCase):
    def test_wants_tasks(self):
        for text in ("quais tarefas eu tenho?", "minhas pendências", "tarefas de carreira", "o que eu preciso pra fazer hoje", "to-do",
                     "o que eu tenho que fazer hoje?", "o que falta fazer", "o que está pendente?"):
            self.assertTrue(wants_tasks(text), text)
        for text in ("oi", "como está o tempo", "me explica o que é um container"):
            self.assertFalse(wants_tasks(text), text)

    def test_query_words(self):
        self.assertEqual(task_query_words("quais tarefas eu tenho?"), [])
        self.assertEqual(task_query_words("tarefas de carreira"), ["carreira"])
        self.assertEqual(task_query_words("e as pendências do Dindin?"), ["dindin"])
        self.assertEqual(task_query_words("domo", min_len=3), ["domo"])
        self.assertEqual(task_query_words("dmo", min_len=3), ["dmo"])
        self.assertEqual(task_query_words("dmo"), [])  # the free-text path keeps the 4-letter minimum


if __name__ == "__main__":
    unittest.main()
