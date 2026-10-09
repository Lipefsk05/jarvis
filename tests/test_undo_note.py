import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from jarvis.inbox import NoteJournal, write_note

NOW = datetime(2026, 10, 9, 12, 0)


class JournalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inbox = self.root / "inbox" / "jarvis"
        self.journal = NoteJournal(self.root / "state" / "notas.json")

    def note(self, text, minute=0):
        path = write_note(self.inbox, text, NOW.replace(minute=minute))
        self.journal.add(path)
        return path

    def test_undoes_only_the_last_note_each_time(self):
        first, second = self.note("comprar queijo", 1), self.note("ir na farmácia", 2)
        name, text = self.journal.undo_last(self.inbox)
        self.assertEqual((name, text), (second.name, "ir na farmácia"))
        self.assertFalse(second.exists())
        self.assertTrue(first.exists())
        self.assertEqual(self.journal.undo_last(self.inbox), (first.name, "comprar queijo"))
        self.assertIsNone(self.journal.undo_last(self.inbox))

    def test_survives_a_restart(self):
        path = self.note("ideia")
        again = NoteJournal(self.root / "state" / "notas.json")
        self.assertEqual(again.undo_last(self.inbox), (path.name, "ideia"))

    def test_note_already_gone_is_reported_not_an_error(self):
        path = self.note("já integrada")
        path.unlink()
        self.assertEqual(self.journal.undo_last(self.inbox), (path.name, None))

    def test_never_touches_notes_it_did_not_write(self):
        mine = self.note("minha")
        other = self.inbox / "2026-01-01-000000-nota.md"
        other.write_text("do Felipe", encoding="utf-8")
        self.journal.undo_last(self.inbox)
        self.assertFalse(mine.exists())
        self.assertTrue(other.exists())

    def test_ignores_names_that_escape_the_inbox(self):
        outside = self.root / "segredo.md"
        outside.write_text("não apagar", encoding="utf-8")
        (self.root / "state").mkdir()
        (self.root / "state" / "notas.json").write_text('["../../segredo.md"]', encoding="utf-8")
        self.assertEqual(self.journal.undo_last(self.inbox), ("../../segredo.md", None))
        self.assertTrue(outside.exists())

    def test_corrupt_journal_means_nothing_to_undo(self):
        (self.root / "state").mkdir()
        (self.root / "state" / "notas.json").write_text("{lixo", encoding="utf-8")
        self.assertIsNone(self.journal.undo_last(self.inbox))


if __name__ == "__main__":
    unittest.main()
