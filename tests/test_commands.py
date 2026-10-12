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
            # the "me" is lost in a transcription or a typo
            "Pode lembrar todas as terças e quintas de ir na aula às 14": "todas as terças e quintas de ir na aula às 14",
            "lembra eu de ligar às 16:30": "de ligar às 16:30",
        }
        # an answer to an offer is not a request: it must reach the model, which has the conversation
        for yes in ("Me lembre sim", "me lembra sim", "pode me lembrar sim", "me lembra sim por favor", "pode lembrar sim"):
            cases[yes] = None
        for text, expected in cases.items():
            self.assertEqual(parse_reminder_request(text), expected, text)

    def test_other_sentences_are_not_reminder_requests(self):
        from jarvis.commands import parse_reminder_request

        for text in ("lembra do que eu falei ontem?", "você lembra da senha?", "eu lembro disso", "lembrar é viver",
                     "bom dia", "anota que preciso de pão"):
            self.assertIsNone(parse_reminder_request(text), text)


class IsYesTest(unittest.TestCase):
    def test_short_agreements(self):
        from jarvis.commands import is_yes

        for text in ("sim", "Sim!", "sim, pode", "pode sim", "Me lembre sim", "me lembra sim por favor", "claro", "isso mesmo", "ok", "bora", "Jarvis, sim"):
            self.assertTrue(is_yes(text), text)

    def test_new_requests_and_denials_are_not_yes(self):
        from jarvis.commands import is_yes

        for text in ("", "não", "sim mas amanhã às 9", "me lembra de pagar a luz", "pode anotar que preciso de pão",
                     "sim, e quanto gastei hoje?", "nao quero", "me lembra amanhã", "claro que não"):
            self.assertFalse(is_yes(text), text)


class IntentGatesTest(unittest.TestCase):
    def test_actions_that_change_things_need_the_users_words(self):
        from jarvis.commands import has_intent

        yes = {
            "cancelar_lembrete": ["cancela o lembrete 3", "apaga o lembrete do dentista", "desmarca o treino", "remove o 3", "esquece o lembrete"],
            "listar_lembretes": ["quais são meus lembretes?", "o que eu tenho marcado?", "lista os lembretes", "meus compromissos"],
            "limpar_conversa": ["esquece a conversa", "limpa tudo", "vamos recomeçar", "zera isso"],
            "anotar": ["anota que preciso de pão", "não esquece de ligar", "guarda isso", "registra aí", "sim", "pode"],
        }
        no = {
            "cancelar_lembrete": ["treinar amanhã de manhã", "Me lembro amanhã às 10", "banana", "tenho dentista amanhã"],
            "listar_lembretes": ["banana", "treinar amanhã de manhã", "oi"],
            "limpar_conversa": ["banana", "treinar amanhã"],
            "anotar": ["o pão acabou", "treinar amanhã de manhã"],
        }
        for action, texts in yes.items():
            for text in texts:
                self.assertTrue(has_intent(action, text), (action, text))
        for action, texts in no.items():
            for text in texts:
                self.assertFalse(has_intent(action, text), (action, text))
        for harmless in ("consultar_tarefas", "ver_gasto", "mostrar_ajuda", "criar_lembrete"):
            self.assertTrue(has_intent(harmless, "qualquer coisa"))


class MisheardReminderTest(unittest.TestCase):
    def test_me_lembro_with_a_time(self):
        from jarvis.reminder_request import parse_misheard_request

        for text in ("Me lembro amanhã às nove de treinar por duas horas.", "Me lembro amanhã às 10 de correr.",
                     "me lembro todo dia às 8 de tomar remédio", "Jarvis, me lembro daqui a 10 minutos de ver o bolo",
                     "pode me lembro amanhã às 9 de ligar"):
            self.assertIsNotNone(parse_misheard_request(text), text)
        for text in ("me lembro que ontem às 9 eu fui lá", "me lembro de tudo", "me lembro quando era criança",
                     "me lembro", "me lembro disso", "me lembra amanhã às 9"):
            self.assertIsNone(parse_misheard_request(text), text)
