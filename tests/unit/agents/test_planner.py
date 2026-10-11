import tempfile
import unittest
from pathlib import Path

from plotline.agents import nl_rules, planner
from plotline.contract import Criteria, RunOptions
from plotline.llm_client import LlmClient
from plotline.orchestrator import Engine
from plotline.state import DataInfo, Failure, L1Request
from plotline.trace import TraceLog
from tests.support import SNAPSHOT_SHA, FakeChat, llm_config, small_df

INFO = DataInfo(first_month="2004-01", latest_month="2015-02")
SMALL_INFO = DataInfo(first_month="2014-01", latest_month="2015-02")  # small_df(): valid ends 2014-12 .. 2015-02
GOOD = '{"localities": ["Adyar"], "window_end": null, "bhk": [1], "price_band": null, "sqft_range": null, "sale_cond": null, "price_unit": "inr"}'


def engine(**kw) -> Engine:
    return Engine(SNAPSHOT_SHA, logic_version="abc1234", **kw)  # default agents: real planner + scanner


def live_engine(*answers) -> tuple[Engine, FakeChat]:
    chat = FakeChat(*answers)
    return engine(llm_client=LlmClient(llm_config("live"), chat=chat)), chat


class StructuredMode(unittest.TestCase):
    def test_defaults_filled_and_input_untouched(self):  # I-PURE
        c = Criteria(localities=["Adyar"])
        c0 = c.model_copy(deep=True)
        p = planner.plan(c, INFO, RunOptions(), 0, "off", TraceLog())
        self.assertEqual((p.effective.window_end, p.effective.price_unit), ("2015-02", "inr"))
        self.assertIsNone(p.criteria_in.window_end)
        self.assertEqual(c, c0)

    def test_topology_rule_and_override(self):
        def topo(locs, force=None):
            p = planner.plan(Criteria(localities=locs), INFO, RunOptions(force_topology=force), 0, "off", TraceLog())
            return p.topology, p.n_scanners
        self.assertEqual(topo(None), ("parallel", 7))
        self.assertEqual(topo(["Adyar", "T Nagar", "Chrompet"]), ("parallel", 3))
        self.assertEqual(topo(["Adyar", "T Nagar"]), ("consolidated", 1))
        self.assertEqual(topo(["Adyar", "Adyar", "T Nagar"]), ("consolidated", 1))  # set semantics
        self.assertEqual(topo(None, "consolidated"), ("consolidated", 1))
        self.assertEqual(topo(["Adyar"], "parallel"), ("parallel", 1))

    def test_no_model_call_in_structured_mode(self):
        e, chat = live_engine(GOOD)
        self.assertEqual(e.run(Criteria(), small_df()).status, "ok")
        self.assertEqual(chat.calls, [])


class Repair(unittest.TestCase):
    def repair(self, criteria: Criteria, issues: list[str], l1_repairs: int = 0):
        p = planner.plan(criteria, INFO, RunOptions(), 0, "off", TraceLog())
        trace = TraceLog()
        out = planner.repair(p, L1Request(issues, []), INFO, RunOptions(), l1_repairs, trace)
        return out, [e for e in trace.events if e.kind == "loop"]

    def test_each_repair(self):
        cases = [
            (Criteria(price_band=[9, 1]), "band_inverted", "price_band", [1, 9]),
            (Criteria(localities=["Adyr", "T Nagar"]), "locality_unknown", "localities", ["Adyar", "T Nagar"]),
            (Criteria(window_end="2016-07"), "window_out_of_range", "window_end", "2015-02"),
            (Criteria(window_end="2004-03"), "window_out_of_range", "window_end", "2004-12"),
            (Criteria(bhk=[0, 2, 7]), "bhk_out_of_range", "bhk", [2]),
        ]
        for criteria, issue, field, expected in cases:
            with self.subTest(issue=issue, criteria=criteria):
                out, loops = self.repair(criteria, [issue])
                self.assertEqual(getattr(out.effective, field), expected)
                self.assertEqual(out.criteria_in, criteria)  # the request as received
                self.assertEqual(len(loops), 1)
                self.assertEqual((loops[0].data["issue"], loops[0].data["after"], loops[0].data["repair_no"]),
                                 (issue, expected, 1))

    def test_several_issues_are_one_repair(self):
        out, loops = self.repair(Criteria(price_band=[9, 1], bhk=[2, 9]), ["band_inverted", "bhk_out_of_range"], 1)
        self.assertEqual((out.effective.price_band, out.effective.bhk), ([1, 9], [2]))
        (ev,) = loops
        self.assertEqual(ev.msg, 'L1 fired: band_inverted+bhk_out_of_range; {"bhk":[2,9],"price_band":[9,1]} '
                                 '-> {"bhk":[2],"price_band":[1,9]}; repair 2 of 2')

    def test_repair_rechooses_topology(self):
        out, _ = self.repair(Criteria(localities=["Adyr", "Velachery", "Chrompet"]), ["locality_unknown"])
        self.assertEqual((out.topology, out.n_scanners), ("parallel", 3))

    def test_cannot_repair(self):
        cases = [
            (Criteria(localities=["Mumbai"]), "locality_unknown", "localities"),
            (Criteria(bhk=[0, 9]), "bhk_out_of_range", "bhk"),
            (Criteria(sale_cond=["Auction"]), "sale_cond_unknown", "sale_cond"),
        ]
        for criteria, issue, field in cases:
            with self.subTest(issue=issue):
                out, loops = self.repair(criteria, [issue])
                self.assertIsInstance(out, Failure)
                self.assertEqual(out.error.code, "E_INVALID_CRITERIA")
                self.assertIn(field, out.error.message)
                self.assertEqual(loops, [])

    def test_unrepairable_issue_blocks_the_whole_pass(self):
        out, loops = self.repair(Criteria(price_band=[9, 1], localities=["Mumbai"]), ["band_inverted", "locality_unknown"])
        self.assertIsInstance(out, Failure)
        self.assertEqual(loops, [])


class ThroughEngine(unittest.TestCase):
    def test_inverted_band_is_repaired(self):
        r = engine().run(Criteria(price_band=[9000000, 1000000]), small_df())
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.criteria_in.price_band, [9000000, 1000000])
        (l1,) = [e for e in r.trace if e.loop == "L1"]
        self.assertEqual((l1.data["before"], l1.data["after"]), ([9000000, 1000000], [1000000, 9000000]))
        self.assertEqual(r.metadata.loop_counters.L1_repairs, 1)
        # small_df has almost no coverage, so L2 then widens the repaired band up to the cap
        self.assertEqual((r.metadata.loop_counters.L2_attempts, r.effective_criteria.price_band), (3, None))

    def test_window_is_clamped_to_the_data(self):
        r = engine().run(Criteria(window_end="2012-01"), small_df())
        self.assertEqual((r.status, r.effective_criteria.window_end), ("ok", "2014-12"))

    def test_unrepairable_is_an_error_report(self):
        r = engine().run(Criteria(localities=["Mumbai"]), small_df())
        self.assertEqual((r.status, r.error.code), ("error", "E_INVALID_CRITERIA"))
        self.assertEqual(r.metadata.loop_counters.L1_repairs, 0)

    def test_loops_disabled_means_no_repair(self):
        r = engine().run(Criteria(price_band=[9, 1]), small_df(), options=RunOptions(loops_enabled=False))
        self.assertEqual((r.status, r.error.code), ("error", "E_INVALID_CRITERIA"))

    def test_scanner_rows_reach_the_trace(self):
        r = engine().run(Criteria(localities=["Adyar", "T Nagar"]), small_df())
        (scan,) = [e for e in r.trace if e.agent == "scanner"]
        self.assertEqual(scan.msg, "scan: 1 scanner(s), consolidated: 1 rows")


class AiMode(unittest.TestCase):
    def test_off_is_e_llm_off(self):
        r = engine().run("Adyar 1 BHK last year", small_df())
        self.assertEqual((r.status, r.error.code, r.criteria_in), ("error", "E_LLM_OFF", None))

    def test_model_answer_becomes_the_criteria(self):
        e, chat = live_engine(GOOD)
        r = e.run("Adyar 1 BHK houses", small_df(), seed=101)
        self.assertEqual(r.status, "ok")
        self.assertEqual((r.criteria_in.localities, r.criteria_in.window_end), (["Adyar"], None))
        self.assertEqual(r.effective_criteria.window_end, "2015-02")
        self.assertEqual(chat.calls[0][2], 101)  # the run seed reaches the client
        self.assertIn('latest month in the data is "2015-02"', chat.calls[0][0])
        self.assertEqual((r.metadata.llm.seed, r.metadata.llm.quant), (101, "Q4_K_M"))

    def test_no_model_call_means_no_llm_metadata(self):
        e, _ = live_engine(GOOD)
        self.assertIsNone(e.run(Criteria(), small_df()).metadata.llm)

    def test_malformed_three_times_falls_back_to_rules(self):
        e, chat = live_engine("not json")
        r = e.run("2 bhk flats in Adyar last year", small_df())
        self.assertEqual(r.status, "ok")
        self.assertEqual(len(chat.calls), 3)
        warnings = [e.msg for e in r.trace if e.kind == "warning"]
        self.assertEqual(len([w for w in warnings if w.startswith("attempt")]), 3)
        self.assertIn("fallback: rule-based parser (model output unusable)", warnings)
        self.assertEqual((r.criteria_in.localities, r.criteria_in.bhk), (["Adyar"], [2]))
        self.assertEqual((r.metadata.loop_counters.L1_repairs, r.metadata.loop_counters.L2_attempts), (0, 0))

    def test_model_and_rules_both_fail(self):
        e, _ = live_engine("not json")
        r = e.run("hello there", small_df())
        self.assertEqual((r.status, r.error.code), ("error", "E_NL_UNPARSEABLE"))

    def test_bad_values_from_the_model_go_to_l1(self):
        e, _ = live_engine(GOOD.replace('"Adyar"', '"Adyr"'))
        r = e.run("Adyr 1 BHK", small_df())
        self.assertEqual((r.status, r.effective_criteria.localities, r.metadata.loop_counters.L1_repairs),
                         ("ok", ["Adyar"], 1))

    def test_replay_miss(self):
        with tempfile.TemporaryDirectory() as d:
            client = LlmClient(llm_config("replay", Path(d) / "c.jsonl"))
            r = engine(llm_client=client).run("Adyar last year", small_df())
        self.assertEqual((r.status, r.error.code), ("error", "E_REPLAY_MISS"))

    def test_replay_is_byte_identical_to_live(self):
        from plotline.contract import report_to_json
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "c.jsonl"
            live = engine(llm_client=LlmClient(llm_config("live", cache, cache_write=True), chat=FakeChat(GOOD)))
            a = live.run("Adyar 1 BHK houses", small_df(), seed=202)
            replay = engine(llm_client=LlmClient(llm_config("replay", cache)))
            b = replay.run("Adyar 1 BHK houses", small_df(), seed=202)
            c = replay.run("Adyar 1 BHK houses", small_df(), seed=202)
        self.assertEqual(report_to_json(b), report_to_json(c))  # I-DET in replay
        self.assertEqual(report_to_json(a).replace('"live"', '"replay"'), report_to_json(b))


class RuleParser(unittest.TestCase):
    def parse(self, s):
        return nl_rules.parse(s, INFO)

    def test_last_year_phrasings(self):
        for s in ["sales last year", "prices over the past year", "trend for the last 12 months", "houses this year"]:
            with self.subTest(s):
                self.assertEqual(self.parse(s).window_end, "2015-02")

    def test_named_month_and_year(self):
        self.assertEqual(self.parse("12 months ending March 2011").window_end, "2011-03")
        self.assertEqual(self.parse("prices ending 2009-06").window_end, "2009-06")
        self.assertEqual(self.parse("house prices in 2012").window_end, "2012-12")

    def test_money_words_become_inr(self):
        self.assertEqual(self.parse("Adyar flats 70 to 90 lakh").price_band, [7000000, 9000000])
        self.assertEqual(self.parse("homes under 1 crore").price_band, [0, 10000000])
        self.assertEqual(self.parse("between 1.5 crore and 2 crore").price_band, [15000000, 20000000])
        self.assertEqual(self.parse("homes under 1 crore").price_unit, "inr")
        self.assertIsNone(self.parse("homes above 1 crore").price_band)

    def test_localities_bhk_sqft_and_sale_condition(self):
        c = self.parse("1 and 2 BHK in T Nagar or Chrompt, 1000-1500 sqft, partial sales")
        self.assertEqual(c.localities, ["Chrompet", "T Nagar"])
        self.assertEqual((c.bhk, c.sqft_range, c.sale_cond), ([1, 2], [1000, 1500], ["Partial"]))
        self.assertEqual(self.parse("march 2011 2 bhk").bhk, [2])

    def test_unparseable(self):
        self.assertIsNone(self.parse("hello there"))
        self.assertEqual(self.parse("show me house prices"), Criteria())


if __name__ == "__main__":
    unittest.main()
