import json
import tempfile
import unittest
from pathlib import Path

from jarvis.config import REPO_ROOT
from jarvis.pronunciation import for_speech, load

TABLE = {"Dindin": "Dindim", "Firebase": "Fáier-beiss", "Next": "Nécsti", "Next.js": "Nécsti jêi-és"}


class ForSpeechTest(unittest.TestCase):
    def test_replaces_whole_words_in_any_capitalisation(self):
        self.assertEqual(for_speech("O Dindin usa Firebase.", TABLE), "O Dindim usa Fáier-beiss.")
        self.assertEqual(for_speech("o dindin e o FIREBASE", TABLE), "o Dindim e o Fáier-beiss")

    def test_does_not_touch_parts_of_other_words(self):
        self.assertEqual(for_speech("Dindinzinho e Firebases", TABLE), "Dindinzinho e Firebases")

    def test_the_longest_entry_wins(self):
        self.assertEqual(for_speech("Next.js é bom", TABLE), "Nécsti jêi-és é bom")

    def test_empty_table_changes_nothing(self):
        self.assertEqual(for_speech("Dindin", {}), "Dindin")

    def test_loading_tolerates_missing_and_broken_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            self.assertEqual(load(path), {})
            path.write_text("{quebrado", encoding="utf-8")
            self.assertEqual(load(path), {})
            path.write_text(json.dumps(["lista"]), encoding="utf-8")
            self.assertEqual(load(path), {})

    def test_the_shipped_table_has_the_chosen_respellings(self):
        table = load(REPO_ROOT / "persona" / "pronuncias.json")
        self.assertEqual(table["Dindin"], "Dindim")
        self.assertEqual(table["Firebase"], "Fáier-beiss")


if __name__ == "__main__":
    unittest.main()
