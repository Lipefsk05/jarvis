import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from jarvis.board import HIGH, LOW, MEDIUM, BoardTask
from jarvis.plan import DONE, NOTEBOOK, PHONE, PLANNED, POSTPONED, DayPlan, PlanItem, PlanStore
from jarvis.planner import (
    advance, complete, find, format_plan, format_week, progress, rebalance,
)

WED = date(2026, 10, 14)
THU = WED + timedelta(days=1)
FRI = WED + timedelta(days=2)
SAT = date(2026, 10, 17)
SUN = date(2026, 10, 18)


def task(title, priority=MEDIUM, area="a", **kw):
    fields = dict(group="pessoal", area=area, section="", title=title, depth=0, priority=priority, idea=False,
                  due=None, task_id="", depends=(), waits=False, needs=NOTEBOOK, needs_marked=False, minutes=0)
    fields.update(kw)
    return BoardTask(**fields)


def many(n, priority=MEDIUM, prefix="t"):
    return [task(f"{prefix}{i}", priority, area=f"area{i}") for i in range(n)]


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "plano.json"
        self.store = PlanStore(self.path)

    def titles(self, day):
        plan = self.store.get(day)
        return [i.title for i in plan.items] if plan else []


class FillTest(Base):
    def test_each_day_holds_the_capacity_and_the_month_is_covered(self):
        rebalance(self.store, many(20), WED)
        self.assertEqual(len(self.titles(WED)), 3)
        self.assertEqual(len(self.titles(THU)), 3)
        self.assertEqual(len(self.titles(SAT)), 0)       # sacred
        self.assertEqual(len(self.titles(SUN)), 2)
        self.assertEqual(sum(len(p.items) for p in self.store.days()), 20)

    def test_the_plan_never_goes_past_the_month(self):
        rebalance(self.store, many(200), WED)
        self.assertLess(max(p.day for p in self.store.days()), WED + timedelta(days=30))

    def test_priority_first_then_the_list(self):
        tasks = [task("baixa", LOW, "x"), task("alta", HIGH, "y"), task("media", MEDIUM, "z"), task("outra", MEDIUM, "w")]
        rebalance(self.store, tasks, WED)
        self.assertEqual(self.titles(WED), ["alta", "media", "outra"])
        self.assertEqual(self.titles(THU), ["baixa"])

    def test_a_close_deadline_beats_priority(self):
        tasks = [task("alta", HIGH, "x"), task("prazo", LOW, "y", due=WED + timedelta(days=2)), task("media", MEDIUM, "z")]
        rebalance(self.store, tasks, WED)
        self.assertEqual(self.titles(WED)[:2], ["prazo", "alta"])

    def test_ideas_blocked_and_subitems_are_never_planned(self):
        tasks = [task("ideia", idea=True), task("sub", depth=1, priority=HIGH),
                 task("espera", waits=True, priority=HIGH), task("ok", priority=LOW)]
        rebalance(self.store, tasks, WED)
        self.assertEqual(self.titles(WED), ["ok"])

    def test_dependency_on_an_open_task_blocks_it(self):
        tasks = [task("base", LOW, task_id="base"), task("depende", HIGH, depends=("base",))]
        rebalance(self.store, tasks, WED)
        self.assertEqual(self.titles(WED), ["base"])

    def test_no_day_is_made_of_one_project(self):
        tasks = [task(f"d{i}", HIGH, "dindin") for i in range(5)] + [task(f"o{i}", MEDIUM, f"o{i}") for i in range(3)]
        rebalance(self.store, tasks, WED)
        areas = [i.area for i in self.store.get(WED).items]
        self.assertLessEqual(areas.count("pessoal/dindin"), 2)
        self.assertEqual(len(areas), 3)

    def test_an_empty_board_changes_nothing(self):
        rebalance(self.store, many(3), WED)
        before = self.titles(WED)
        rebalance(self.store, [], WED)
        self.assertEqual(self.titles(WED), before)

    def test_today_is_steady_but_tomorrow_follows_a_new_priority(self):
        tasks = many(8)
        rebalance(self.store, tasks, WED)
        today = self.titles(WED)
        urgent = task("urgente", HIGH, "novo")
        rebalance(self.store, tasks + [urgent], WED)
        self.assertEqual(self.titles(WED), today)
        self.assertEqual(self.titles(THU)[0], "urgente")

    def test_a_task_that_left_the_board_leaves_the_future(self):
        tasks = many(8)
        rebalance(self.store, tasks, WED)
        gone = self.titles(THU)[0]
        rebalance(self.store, [t for t in tasks if t.title != gone], WED)
        self.assertNotIn(gone, [i.title for p in self.store.days() for i in p.items])

    def test_one_that_left_today_was_ticked_in_the_mind(self):
        tasks = many(5)
        rebalance(self.store, tasks, WED)
        ticked = self.titles(WED)[0]
        rebalance(self.store, [t for t in tasks if t.title != ticked], WED)
        self.assertEqual({i.title: i.status for i in self.store.get(WED).items}[ticked], DONE)


class MidnightTest(Base):
    def test_what_was_not_done_rolls_to_today_first(self):
        tasks = many(8, MEDIUM)
        rebalance(self.store, tasks, WED)
        rebalance(self.store, tasks, THU)             # Wednesday's three were not done: they come first today
        self.assertEqual(self.titles(THU), ["t0", "t1", "t2"])
        self.store.get(THU).items[0].status = DONE    # he finishes one of them
        rebalance(self.store, tasks, FRI)
        self.assertEqual([i.status for i in self.store.get(THU).items], [DONE, POSTPONED, POSTPONED])
        self.assertEqual(self.titles(FRI)[:2], ["t1", "t2"])  # the slipped ones come before everything else

    def test_two_full_days_raise_the_capacity_two_short_days_lower_it(self):
        tasks = many(40)
        rebalance(self.store, tasks, WED)
        for n, day in enumerate((THU, FRI), start=1):
            rebalance(self.store, tasks, day)         # settles the day before
            for item in self.store.get(day).items:
                item.status = DONE
        rebalance(self.store, tasks, SUN)             # Thu, Fri judged (Saturday is sacred and has no plan)
        self.assertEqual(self.store.load.base, 4)
        monday = date(2026, 10, 19)
        rebalance(self.store, tasks, monday)          # Sunday left over
        tue, wed = monday + timedelta(days=1), monday + timedelta(days=2)
        rebalance(self.store, tasks, tue)             # Monday left over
        rebalance(self.store, tasks, wed)             # Tuesday left over
        self.assertEqual(self.store.load.base, 3)

    def test_the_first_run_judges_nothing(self):
        self.store.put(DayPlan(WED, [PlanItem("^x", "velho", NOTEBOOK)]), WED)
        rebalance(self.store, many(3), THU)
        self.assertEqual((self.store.load.base, self.store.load.short), (3, 0))
        self.assertEqual(self.store.load.settled, WED)

    def test_ticked_in_the_mind_counts_as_done_when_the_day_closes(self):
        tasks = many(6)
        rebalance(self.store, tasks, WED)
        rebalance(self.store, tasks, THU)
        plan_thu = [i.title for i in self.store.get(THU).items]
        rebalance(self.store, [t for t in tasks if t.title not in plan_thu], FRI)
        self.assertTrue(all(i.status == DONE for i in self.store.get(THU).items))
        self.assertEqual(self.store.load.full, 1)

    def test_a_day_with_nothing_planned_is_not_judged(self):
        rebalance(self.store, many(1), WED)
        rebalance(self.store, many(1), THU)
        rebalance(self.store, many(1), SUN)  # Fri/Sat had nothing: no streak either way
        self.assertEqual((self.store.load.full, self.store.load.short), (0, 0))

    def test_rebalanced_is_recorded_for_the_daily_check(self):
        rebalance(self.store, many(2), WED)
        self.assertEqual(self.store.load.rebalanced, WED)


class DoneTest(Base):
    def setUp(self):
        super().setUp()
        self.tasks = [task("Landing do Dindin", HIGH, "dindin", task_id="landing-dindin"),
                      task("Pagar o aluguel", HIGH, "casa"), task("Estudar inglês", MEDIUM, "estudo"),
                      task("Relatório do estágio", MEDIUM, "estagio"), task("Revisar relatório mensal", LOW, "outro")]
        rebalance(self.store, self.tasks, WED)

    def test_finding_by_a_few_words(self):
        got = complete(self.store, self.tasks, WED, "a landing do dindin")
        self.assertEqual((got.kind, got.item.task_id), ("done", "^landing-dindin"))
        self.assertEqual(self.store.get(WED).items[0].status, DONE)

    def test_a_typo_is_forgiven(self):
        got = complete(self.store, self.tasks, WED, "pagar aluguell")
        self.assertEqual(got.item.title, "Pagar o aluguel")

    def test_two_equally_good_matches_ask(self):
        got = complete(self.store, self.tasks, WED, "relatório")
        self.assertEqual(got.kind, "many")
        self.assertEqual(len(got.options), 2)

    def test_unknown_task(self):
        self.assertEqual(complete(self.store, self.tasks, WED, "trocar o pneu do carro").kind, "none")

    def test_saying_it_twice(self):
        complete(self.store, self.tasks, WED, "landing dindin")
        self.assertEqual(complete(self.store, self.tasks, WED, "landing dindin").kind, "again")

    def test_a_task_planned_for_another_day_moves_to_today(self):
        tomorrow = self.store.get(THU).items[0]
        got = complete(self.store, self.tasks, WED, tomorrow.title)
        self.assertEqual(got.kind, "done")
        self.assertIn(tomorrow.title, self.titles(WED))
        self.assertNotIn(tomorrow.title, self.titles(THU))

    def test_a_board_task_outside_the_plan_still_counts(self):
        tasks = many(100, MEDIUM, "x") + [task("Consertar a bike", LOW, "bike")]
        rebalance(self.store, tasks, WED)
        in_plan = {i.title for p in self.store.days() for i in p.items}
        self.assertNotIn("Consertar a bike", in_plan)
        got = complete(self.store, tasks, WED, "consertar bike")
        self.assertEqual(got.kind, "done")
        self.assertEqual(self.store.get(WED).items[-1].status, DONE)

    def test_done_by_the_jarvis_stays_out_of_the_pool_until_the_board_catches_up(self):
        complete(self.store, self.tasks, WED, "pagar aluguel")
        rebalance(self.store, self.tasks, WED)   # the board still lists it as open
        everywhere = [i.title for p in self.store.days() for i in p.items if i.status == PLANNED]
        self.assertNotIn("Pagar o aluguel", everywhere)


class AdvanceTest(Base):
    def test_pulls_the_next_planned_task_into_today(self):
        tasks = many(8)
        rebalance(self.store, tasks, WED)
        nxt = self.titles(THU)[0]
        item = advance(self.store, WED)
        self.assertEqual(item.title, nxt)
        self.assertIn(nxt, self.titles(WED))
        self.assertEqual(len(self.titles(WED)), 4)
        rebalance(self.store, tasks, WED)    # the next recomputation keeps it
        self.assertIn(nxt, self.titles(WED))
        self.assertEqual(len([t for p in self.store.days() for t in p.items if t.title == nxt]), 1)

    def test_nothing_ahead(self):
        rebalance(self.store, many(2), WED)
        self.assertIsNone(advance(self.store, WED))


class TextTest(Base):
    def test_saturday_is_rest(self):
        self.assertIn("sábado", format_plan(None, self.store, SAT))

    def test_today_with_progress_and_a_look_at_tomorrow(self):
        tasks = [task(w, area=w) for w in ("alfa", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel")]
        rebalance(self.store, tasks, WED)
        complete(self.store, tasks, WED, self.titles(WED)[0])
        text = format_plan(self.store.get(WED), self.store, WED)
        self.assertIn("✅", text)
        self.assertIn("Feitas: 1 de 3.", text)
        self.assertIn("qui 15/10", text)
        self.assertEqual(progress(self.store.get(WED)), "1 de 3")

    def test_nothing_pending(self):
        self.assertIn("nada pendente", format_plan(None, self.store, WED))

    def test_the_week(self):
        rebalance(self.store, many(8), WED)
        text = format_week(self.store, WED)
        self.assertIn("qua 14/10", text)
        self.assertNotIn("sáb", text)

    def test_minutes_only_when_known(self):
        rebalance(self.store, [task("curta", minutes=30), task("sem", area="b")], WED)
        text = format_plan(self.store.get(WED), self.store, WED)
        self.assertIn("(~30 min)", text)
        self.assertEqual(text.count("min)"), 1)


class FindTest(unittest.TestCase):
    entries = [("a", "Landing do Dindin"), ("b", "Relatório do estágio"), ("c", "Relatório mensal")]

    def test_words_are_matched_without_accents(self):
        self.assertEqual(find("landing", self.entries).entries, (("a", "Landing do Dindin"),))
        self.assertEqual(find("estagio", self.entries).entries[0][0], "b")

    def test_short_noise_words_do_not_match(self):
        self.assertEqual(find("do de da", self.entries).kind, "none")

    def test_half_a_match_is_not_enough(self):
        self.assertEqual(find("landing do site novo da loja", self.entries).kind, "none")


if __name__ == "__main__":
    unittest.main()


class StudyTaskTest(Base):
    def test_a_study_task_is_dropped_from_a_plan_made_before_it_was_marked(self):
        english, bills = task("Inglês fluente", HIGH, area="carreira"), task("Pagar luz", HIGH, area="casa")
        rebalance(self.store, [english, bills], WED)
        self.assertIn("Inglês fluente", [i.title for i in self.store.get(WED).items])
        marked = task("Inglês fluente", HIGH, area="carreira", study=True)  # the Felipe marks it 📚 later
        rebalance(self.store, [marked, bills], WED)
        every = [i.title for plan in self.store.days() for i in plan.items]
        self.assertNotIn("Inglês fluente", every)
        self.assertIn("Pagar luz", every)
