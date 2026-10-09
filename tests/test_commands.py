import unittest

from jarvis.commands import parse_note_request


class ParseNoteRequestTest(unittest.TestCase):
    def test_note_requests(self):
        self.assertEqual(parse_note_request("anota comprar café"), "comprar café")
        self.assertEqual(parse_note_request("Anota: ligar pro Matheus"), "ligar pro Matheus")
        self.assertEqual(parse_note_request("  anote - revisar o contrato"), "revisar o contrato")
        self.assertEqual(parse_note_request("anotar isso\nem duas linhas"), "em duas linhas")  # "isso" points at what follows
        self.assertEqual(parse_note_request("anota comprar pão\ne leite"), "comprar pão\ne leite")  # multi-line notes keep every line
        self.assertEqual(parse_note_request("anota que preciso comprar queijo"), "preciso comprar queijo")
        self.assertEqual(parse_note_request("anota aí: ligar pro banco"), "ligar pro banco")
        self.assertEqual(parse_note_request("anota quebrar o gelo"), "quebrar o gelo")  # "que" only as a whole word

    def test_other_ways_of_asking_for_a_note(self):
        cases = {
            "pode anotar que preciso comprar pão": "preciso comprar pão",
            "Preciso anotar: ligar pro banco": "ligar pro banco",
            "vc pode anotar isso: reunião às 10": "reunião às 10",
            "quero anotar uma ideia pro app": "uma ideia pro app",
            "registra aí que o deploy é sexta": "o deploy é sexta",
            "guarda isso: senha do wifi é a de casa": "senha do wifi é a de casa",
            "salva isso pra mim: ver o contrato": "ver o contrato",
        }
        for text, expected in cases.items():
            self.assertEqual(parse_note_request(text), expected, text)

    def test_ambiguous_verbs_without_isso_are_not_notes(self):
        for text in ("guarda o notebook na mochila", "salva meu dia", "registra o domínio da empresa", "me lembra de ligar pro banco",
                     "não esquece de ligar pro Matheus", "pode explicar o que é um webhook"):
            self.assertIsNone(parse_note_request(text), text)

    def test_bare_word_asks_what_to_note(self):
        self.assertEqual(parse_note_request("anota"), "")
        self.assertEqual(parse_note_request("anota:"), "")

    def test_other_sentences_go_to_the_model(self):
        for text in ("oi", "anotaram tudo errado", "me ajuda a anotar", "não anota isso"):
            self.assertIsNone(parse_note_request(text), text)


if __name__ == "__main__":
    unittest.main()


class ReminderRequestTest(unittest.TestCase):
    def test_me_lembra_starts_a_request(self):
        from jarvis.commands import parse_reminder_request

        cases = {
            "me lembra de pagar a luz amanhã às 9": "de pagar a luz amanhã às 9",
            "Jarvis, me lembra hoje às 19 da reunião": "hoje às 19 da reunião",
            "pode me lembrar amanhã às 8 do remédio": "amanhã às 8 do remédio",
            "lembra-me de ligar": "de ligar",
            "me lembra": "",
        }
        for text, expected in cases.items():
            self.assertEqual(parse_reminder_request(text), expected, text)

    def test_other_sentences_are_not_reminder_requests(self):
        from jarvis.commands import parse_reminder_request

        for text in ("lembra do que eu falei ontem?", "você lembra da senha?", "eu lembro disso", "lembrar é viver",
                     "bom dia", "anota que preciso de pão"):
            self.assertIsNone(parse_reminder_request(text), text)
