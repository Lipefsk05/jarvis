import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from jarvis.agenda import (Account, account_question, listing, merge, overlapping, parse_accounts, pick_account,
                           search, window)
from jarvis.gcal import Event
from jarvis.when import Ask

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 16, 10, 0, tzinfo=TZ)  # a Friday
ACCOUNTS = parse_accounts("trabalho=a@x.com, pessoal=b@y.com, cafe=admin@cafelabs.net")
WORK, PERSONAL, CAFE = ACCOUNTS


def event(title, hour, calendar="a@x.com", minutes=60, day=16, all_day=False):
    start = datetime(2026, 10, day, hour, 0, tzinfo=TZ)
    return Event("id" + title, calendar, title, start, start + timedelta(minutes=minutes), all_day)


class AccountsTest(unittest.TestCase):
    def test_parses_the_three_accounts_in_order_and_skips_bad_pieces(self):
        self.assertEqual([a.key for a in ACCOUNTS], ["trabalho", "pessoal", "cafe"])
        self.assertEqual(CAFE.label, "Café Labs")
        self.assertEqual(parse_accounts("sem-arroba=x, =a@b.com, trabalho=a@b.com, trabalho=c@d.com"),
                         (Account("trabalho", "profissional", "a@b.com"),))
        self.assertEqual(parse_accounts(None), ())

    def test_explicit_words_beat_guesses(self):
        self.assertEqual(pick_account("reunião pessoal com a Ana", ACCOUNTS), PERSONAL)
        self.assertEqual(pick_account("marca na agenda da Café", ACCOUNTS), CAFE)
        self.assertEqual(pick_account("evento de trabalho", ACCOUNTS), WORK)

    def test_the_subject_only_counts_when_guessing_is_turned_on(self):
        self.assertEqual(pick_account("reunião com o cliente amanhã", ACCOUNTS, guess=True), CAFE)
        self.assertEqual(pick_account("viagem pra Floripa", ACCOUNTS, guess=True), PERSONAL)
        self.assertEqual(pick_account("dentista às 14", ACCOUNTS, guess=True), PERSONAL)
        for text in ("reunião com o cliente amanhã", "viagem pra Floripa", "dentista às 14"):
            self.assertIsNone(pick_account(text, ACCOUNTS), text)  # the default is to ask

    def test_nothing_or_two_answers_means_ask(self):
        self.assertIsNone(pick_account("almoço amanhã", ACCOUNTS))
        self.assertIsNone(pick_account("reunião no dentista", ACCOUNTS, guess=True))  # cafe vs pessoal
        self.assertIsNone(pick_account("qualquer coisa", ()))

    def test_the_question_names_every_account(self):
        self.assertEqual(account_question(ACCOUNTS), "Em qual agenda, senhor: profissional, pessoal ou Café Labs?")


class WindowTest(unittest.TestCase):
    def test_days(self):
        start, end, label = window("", NOW)
        self.assertEqual((start, end, label), (datetime(2026, 10, 16, tzinfo=TZ), datetime(2026, 10, 17, tzinfo=TZ), "hoje"))
        self.assertEqual(window("amanhã", NOW)[2:], ("amanhã",))
        self.assertEqual(window("amanhã", NOW)[0], datetime(2026, 10, 17, tzinfo=TZ))
        start, end, label = window("segunda", NOW)
        self.assertEqual((start.day, label), (19, "segunda-feira, 19/10"))

    def test_week_and_unknown(self):
        start, end, label = window("essa semana", NOW)
        self.assertEqual((end - start).days, 7)
        self.assertTrue(label.startswith("nos"))
        self.assertIsInstance(window("blablabla", NOW), Ask)

    def test_today_still_works_after_noon(self):
        late = NOW.replace(hour=20)
        self.assertEqual(window("hoje", late)[0], datetime(2026, 10, 16, tzinfo=TZ))
        self.assertEqual(window("", late)[2], "hoje")


class MergeAndListTest(unittest.TestCase):
    def test_the_same_event_in_two_accounts_shows_once_with_both(self):
        shown = merge([(WORK, [event("Reunião Foo", 15)]), (CAFE, [event("reunião foo", 15, "admin@cafelabs.net")])])
        self.assertEqual(len(shown), 1)
        self.assertEqual({a.key for a in shown[0].accounts}, {"trabalho", "cafe"})

    def test_ordered_by_time(self):
        shown = merge([(WORK, [event("B", 15)]), (PERSONAL, [event("A", 9, "b@y.com")])])
        self.assertEqual([s.event.title for s in shown], ["A", "B"])

    def test_listing_one_day(self):
        text = listing(merge([(WORK, [event("Dentista", 9)])]), "hoje", NOW)
        self.assertEqual(text, "Agenda de hoje, senhor:\n• 09:00–10:00  Dentista (profissional)")

    def test_listing_says_when_empty_and_when_an_account_failed(self):
        self.assertEqual(listing([], "amanhã", NOW), "Não há nada marcado amanhã, senhor.")
        self.assertIn("Não consegui ler: Café Labs.", listing([], "hoje", NOW, failed=[CAFE]))

    def test_listing_several_days_groups_by_day(self):
        shown = merge([(WORK, [event("A", 9), event("B", 9, day=17)])])
        text = listing(shown, "nos próximos 7 dias", NOW)
        self.assertIn("Hoje:", text)
        self.assertIn("Amanhã:", text)

    def test_all_day_event(self):
        text = listing(merge([(PERSONAL, [event("Feriado", 0, "b@y.com", 1440, all_day=True)])]), "hoje", NOW)
        self.assertIn("dia todo  Feriado", text)


class OverlapAndSearchTest(unittest.TestCase):
    def setUp(self):
        self.shown = merge([(WORK, [event("Reunião Foo", 15), event("Feriado", 0, minutes=1440, all_day=True)])])

    def test_overlap_ignores_all_day_and_touching_events(self):
        start = datetime(2026, 10, 16, 15, 30, tzinfo=TZ)
        self.assertEqual([s.event.title for s in overlapping(self.shown, start, start + timedelta(hours=1))], ["Reunião Foo"])
        end_of_it = datetime(2026, 10, 16, 16, 0, tzinfo=TZ)
        self.assertEqual(overlapping(self.shown, end_of_it, end_of_it + timedelta(hours=1)), [])

    def test_search_needs_every_word_and_ignores_accents(self):
        self.assertEqual(len(search(self.shown, "reuniao foo")), 1)
        self.assertEqual(search(self.shown, "reunião bar"), [])
        self.assertEqual(search(self.shown, "de a"), [])  # only tiny words: nothing to look for


if __name__ == "__main__":
    unittest.main()
