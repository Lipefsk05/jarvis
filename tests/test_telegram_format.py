import unittest

from jarvis.mind import Task, select
from jarvis.telegram_format import MAX_MESSAGE_CHARS, format_items, format_summary, safe


def t(group, area, section, title):
    return Task(group, area, section, title)


TASKS = [
    t("pessoal", "carreira", "Vaga", "Candidatura CLT"),
    t("empresa", "dindin", "Rodada Forge", "docs NÃO rodou"),
    t("empresa", "dindin", "Rodada Forge", "Linkar /privacidade no Play Console"),
    t("empresa", "dindin", "Feedback dos testadores", "Filtro de datas <invertido> & outros"),
    t("empresa", "domo", "Geral", "Publicar"),
]


class SafeTest(unittest.TestCase):
    def test_escapes_html_and_defuses_slash_words(self):
        self.assertEqual(safe("a <b> & c"), "a &lt;b&gt; &amp; c")
        self.assertEqual(safe("ver /privacidade agora"), "ver /\u200bprivacidade agora")
        self.assertEqual(safe("pasta a/b e http://x.y"), "pasta a/b e http://x.y")  # only standalone /word


class SummaryTest(unittest.TestCase):
    def test_grouped_one_area_per_line_with_counts(self):
        text = format_summary(TASKS)
        self.assertIn("<b>Pessoal</b>\n• carreira — 1", text)
        self.assertIn("<b>Empresa</b>\n• dindin — 3\n• domo — 1", text)
        self.assertIn("Total: 5", text)
        self.assertNotIn(" — 1; ", text)  # no more run-on "area: n; area: n"

    def test_empty(self):
        self.assertIn("Nenhuma pendência", format_summary([]))


class ItemsTest(unittest.TestCase):
    def test_groups_by_section_numbers_continuously_and_hides_the_repeated_prefix(self):
        dindin = [x for x in TASKS if x.area == "dindin"]
        text = format_items(dindin)
        self.assertTrue(text.startswith("<b>3 pendências em dindin</b>"))
        self.assertIn("<b>Rodada Forge</b> (2)\n1. docs NÃO rodou\n2. Linkar /\u200bprivacidade no Play Console", text)
        self.assertIn("<b>Feedback dos testadores</b> (1)\n3. Filtro de datas &lt;invertido&gt; &amp; outros", text)
        self.assertNotIn("[dindin >", text)

    def test_several_areas_prefix_the_section_with_the_area(self):
        text = format_items([x for x in TASKS if x.group == "empresa" and x.area in ("dindin", "domo")][:1] + [TASKS[4]])
        self.assertIn("dindin › Rodada Forge", text)
        self.assertIn("domo › Geral", text)

    def test_limit_footer_tells_how_to_narrow(self):
        text = format_items(TASKS[1:4], limit=2)
        self.assertIn("Mostrando 2 de 3", text)
        self.assertIn("/tarefas dindin palavra-da-seção", text.replace("/\u200b", "/"))
        self.assertNotIn("3. Filtro", text)

    def test_never_exceeds_the_telegram_limit(self):
        many = [t("empresa", "dindin", "S", "titulo " * 15) for _ in range(300)]
        self.assertLessEqual(len(format_items(many, limit=300)), MAX_MESSAGE_CHARS + 2)


class NarrowingTest(unittest.TestCase):
    def test_extra_words_narrow_the_selection(self):
        self.assertEqual(len(select(TASKS, ["dindin"])), 3)
        self.assertEqual(len(select(TASKS, ["dindin", "feedback"])), 1)

    def test_falls_back_to_any_word_when_no_task_matches_all(self):
        self.assertEqual(len(select(TASKS, ["carreira", "domo"])), 2)


if __name__ == "__main__":
    unittest.main()
