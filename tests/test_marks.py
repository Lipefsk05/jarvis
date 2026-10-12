import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.actions import parse_action
from jarvis.commands import has_intent
from jarvis.marks import MarkAsk, confirmation, parse_moment, resolve_ambiguous
from jarvis.plan import Habits
from jarvis.talker.base import ToolCall

TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 14, 9, 45, tzinfo=TZ)


def at(h, m=0):
    return datetime(2026, 10, 14, h, m, tzinfo=TZ)


class MomentTest(unittest.TestCase):
    def test_now_and_empty(self):
        self.assertEqual(parse_moment("", NOW), NOW)
        self.assertEqual(parse_moment("agora", NOW), NOW)

    def test_clock_times(self):
        for text, expected in (("9:40", at(9, 40)), ("às 9", at(9)), ("9h15", at(9, 15))):
            self.assertEqual(parse_moment(text, NOW), expected, text)

    def test_ago(self):
        self.assertEqual(parse_moment("há 10 minutos", NOW), at(9, 35))
        self.assertEqual(parse_moment("faz 1 hora", NOW), at(8, 45))

    def test_future_and_nonsense_are_asked(self):
        for text in ("22:00", "25h", "banana"):
            self.assertIsInstance(parse_moment(text, NOW), MarkAsk, text)


class AmbiguousTest(unittest.TestCase):
    def test_arrived_in_the_morning_with_nothing_told_is_work(self):
        self.assertEqual(resolve_ambiguous("chegada", {}, NOW), "arrive_work")

    def test_arrived_after_leaving_work_is_home(self):
        self.assertEqual(resolve_ambiguous("chegada", {"leave_work": at(15)}, at(16)), "arrive_home")

    def test_arrived_after_leaving_home_is_work(self):
        self.assertEqual(resolve_ambiguous("chegada", {"leave_home": at(8, 30)}, at(15)), "arrive_work")

    def test_arrived_unclear_asks(self):
        self.assertIsInstance(resolve_ambiguous("chegada", {}, at(18)), MarkAsk)

    def test_left_after_arriving_at_work_is_leaving_work(self):
        self.assertEqual(resolve_ambiguous("saida", {"arrive_work": at(9)}, at(15)), "leave_work")

    def test_left_early_with_nothing_told_is_leaving_home(self):
        self.assertEqual(resolve_ambiguous("saida", {}, at(8)), "leave_home")
        self.assertIsInstance(resolve_ambiguous("saida", {}, at(17)), MarkAsk)


class ConfirmationTest(unittest.TestCase):
    def test_arrival_says_when_the_workday_ends(self):
        text = confirmation("arrive_work", at(9, 40), {"arrive_work": at(9, 40)}, Habits(), TZ)
        self.assertIn("chegou ao trabalho às 09:40", text)
        self.assertIn("15:40", text)

    def test_leaving_home_says_when_arriving(self):
        text = confirmation("leave_home", at(8, 15), {"leave_home": at(8, 15)}, Habits(), TZ)
        self.assertIn("09:05", text)


class ActionTest(unittest.TestCase):
    def test_parse_valid_and_invalid(self):
        ok = parse_action(ToolCall("avisar_marco", {"marco": "chegada_casa", "hora": "há 5 minutos"}))
        self.assertEqual((ok.marco, ok.quando), ("chegada_casa", "há 5 minutos"))
        self.assertIsNone(parse_action(ToolCall("avisar_marco", {"marco": "voando"})))

    def test_intent_needs_the_users_words(self):
        for text in ("cheguei no trampo", "saí agora", "to saindo de casa", "desci do ônibus, cheguei em casa"):
            self.assertTrue(has_intent("avisar_marco", text), text)
        self.assertFalse(has_intent("avisar_marco", "o que tem pra fazer hoje?"))


if __name__ == "__main__":
    unittest.main()


class AnswerPlaceTest(unittest.TestCase):
    def test_short_answers_resolve_the_mark(self):
        from jarvis.marks import answer_place
        self.assertEqual(answer_place("chegada", "Em casa"), "chegada_casa")
        self.assertEqual(answer_place("chegada", "no trampo"), "chegada_trabalho")
        self.assertEqual(answer_place("saida", "do trabalho"), "saida_trabalho")
        self.assertEqual(answer_place("saida", "de casa"), "saida_casa")

    def test_not_a_plain_answer(self):
        from jarvis.marks import answer_place
        self.assertIsNone(answer_place("chegada", "casa ou trabalho, não sei"))
        self.assertIsNone(answer_place("chegada", "que horas são?"))
        self.assertIsNone(answer_place("chegada", "preciso resolver uma coisa em casa depois do trabalho amanhã cedo"))


class SkippedStepTest(unittest.TestCase):
    def test_home_without_leaving_work_asks_about_leaving_work(self):
        from jarvis.marks import ask_missing, missing_step
        step = missing_step("arrive_home", {"arrive_home": at(17)})
        self.assertEqual(step, "leave_work")
        self.assertIn("saída do trabalho", ask_missing(step))

    def test_nothing_to_ask_when_the_step_was_told_or_there_is_none(self):
        from jarvis.marks import missing_step
        self.assertIsNone(missing_step("arrive_home", {"leave_work": at(16), "arrive_home": at(17)}))
        self.assertIsNone(missing_step("arrive_work", {"arrive_work": at(9)}))
        self.assertIsNone(missing_step("leave_home", {}))

    def test_answer_time_only_for_short_time_like_replies(self):
        from jarvis.marks import answer_time
        evening = at(18)
        self.assertEqual(answer_time("15:40", evening), at(15, 40))
        self.assertEqual(answer_time("às 15h", evening), at(15))
        self.assertIsNone(answer_time("não lembro", evening))
        self.assertIsNone(answer_time("me lembra de pagar o aluguel amanhã às 10", evening))
        self.assertIsNone(answer_time("20:00", evening))  # still ahead: not an answer
