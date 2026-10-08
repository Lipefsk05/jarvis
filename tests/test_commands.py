import unittest

from jarvis.commands import parse_note_request


class ParseNoteRequestTest(unittest.TestCase):
    def test_note_requests(self):
        self.assertEqual(parse_note_request("anota comprar café"), "comprar café")
        self.assertEqual(parse_note_request("Anota: ligar pro Matheus"), "ligar pro Matheus")
        self.assertEqual(parse_note_request("  anote - revisar o contrato"), "revisar o contrato")
        self.assertEqual(parse_note_request("anotar isso\nem duas linhas"), "isso\nem duas linhas")
        self.assertEqual(parse_note_request("anota que preciso comprar queijo"), "preciso comprar queijo")
        self.assertEqual(parse_note_request("anota aí: ligar pro banco"), "ligar pro banco")
        self.assertEqual(parse_note_request("anota quebrar o gelo"), "quebrar o gelo")  # "que" only as a whole word

    def test_bare_word_asks_what_to_note(self):
        self.assertEqual(parse_note_request("anota"), "")
        self.assertEqual(parse_note_request("anota:"), "")

    def test_other_sentences_go_to_the_model(self):
        for text in ("oi", "anotaram tudo errado", "me ajuda a anotar", "não anota isso"):
            self.assertIsNone(parse_note_request(text), text)


if __name__ == "__main__":
    unittest.main()
