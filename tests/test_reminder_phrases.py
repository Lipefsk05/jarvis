"""Regression corpus: real-sounding "me lembra ..." sentences and what each must become.
Each sentence that went wrong on the phone is added here with the right answer."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.commands import parse_reminder_request
from jarvis.reminder_request import Planned, plan_reminder
from jarvis.when import Ask

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 11, 15, 0, tzinfo=TZ)  # domingo

# sentence -> (text, day, month, hour, minute, repeat)
PLANNED = {
    "me lembra de ligar pro joão amanhã de manhã": ("ligar pro joão", 12, 10, 9, 0, None),
    "me lembra amanhã cedo de pagar a luz": ("pagar a luz", 12, 10, 7, 0, None),
    "me lembra amanhã de tarde de buscar o bolo": ("buscar o bolo", 12, 10, 15, 0, None),
    "me lembra hoje à noite de ligar pra minha mãe": ("ligar pra minha mãe", 11, 10, 20, 0, None),
    "me lembra de manhã de tomar vitamina": ("tomar vitamina", 12, 10, 9, 0, None),
    "me lembra em 1 hora e meia de ver o bolo": ("ver o bolo", 11, 10, 16, 30, None),
    "me lembra daqui a duas horas e meia de ver o bolo": ("ver o bolo", 11, 10, 17, 30, None),
    "me lembra às nove da noite de fechar o caixa": ("fechar o caixa", 11, 10, 21, 0, None),
    "me lembra de orar todo dia ao meio dia": ("orar", 12, 10, 12, 0, "daily"),
    "me lembra todos os dias as 13: Oração": ("Oração", 12, 10, 13, 0, "daily"),
    "me lembra na sexta que vou ao médico às 14h": ("vou ao médico", 16, 10, 14, 0, None),
    "me lembra sábado que vem de comprar presente": ("comprar presente", 17, 10, 9, 0, None),
    "me lembra às 8:30 da manhã de amanhã de tomar remédio": ("tomar remédio", 12, 10, 8, 30, None),
    "me lembra do dentista amanhã às 14": ("dentista", 12, 10, 14, 0, None),
    # as the audio transcription writes them: question mark at the end, "uma", "à tarde", "às sete da manhã"
    "Me lembra em uma hora e meia de ver o bolo?": ("ver o bolo", 11, 10, 16, 30, None),
    "Me lembra amanhã à tarde de buscar o bolo?": ("buscar o bolo", 12, 10, 15, 0, None),
}
# sentence -> the kind of question the code must ask instead of guessing
ASKED = {
    "me lembra toda segunda e quarta às 7 de treinar": "repeticao",
    "Pode me lembrar toda segunda e quarta de manhã, às sete da manhã, treinar?": "repeticao",
    "me lembra todo sábado e domingo às 10 de correr": "repeticao",
    "me lembra de a cada 2 horas beber água": "repeticao",
    "me lembra de 2 em 2 horas de beber água": "repeticao",
    "me lembra todo mês dia 5 de pagar o cartão": "repeticao",
    "me lembra semana que vem de ligar pro Matheus": "entendi",
}


def plan(sentence):
    raw = parse_reminder_request(sentence)
    assert raw is not None, sentence
    return plan_reminder(raw, NOW, 9)


class PhraseCorpusTest(unittest.TestCase):
    def test_planned(self):
        for sentence, (text, day, month, hour, minute, repeat) in PLANNED.items():
            with self.subTest(sentence):
                got = plan(sentence)
                self.assertIsInstance(got, Planned, got)
                self.assertEqual(got.text, text)
                self.assertEqual((got.due.day, got.due.month, got.due.hour, got.due.minute), (day, month, hour, minute))
                self.assertEqual(got.repeat, repeat)

    def test_asks_instead_of_guessing(self):
        for sentence, kind in ASKED.items():
            with self.subTest(sentence):
                got = plan(sentence)
                self.assertIsInstance(got, Ask, got)
                self.assertEqual(got.kind, kind)

    def test_part_of_day_says_the_hour_was_assumed(self):
        self.assertTrue(plan("me lembra amanhã de tarde de buscar o bolo").hour_assumed)
        self.assertFalse(plan("me lembra amanhã às 15 de buscar o bolo").hour_assumed)


if __name__ == "__main__":
    unittest.main()
