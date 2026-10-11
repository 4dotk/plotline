import hashlib
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd

from plotline.contract import (
    CANONICAL_LOCALITIES, Criteria, RunOptions, TrendReport, report_to_json, window_months,
)
from plotline.agents import stubs
from plotline.orchestrator import Engine, run
from plotline.state import CoverageDecision, Failure, L1Request
from tests.support import SNAPSHOT_SHA, small_df


def engine(**kw) -> Engine:
    """These tests check the orchestration itself, so they pin the stub agents
    unless a test passes its own (the real agents have their own test files)."""
    kw.setdefault("agents", stubs.stub_agents())
    return Engine(SNAPSHOT_SHA, logic_version="abc1234", **kw)


class StubEngine(unittest.TestCase):
    """Goal: the stub returns a valid, contract-shaped response."""

    def test_default_request_returns_valid_report(self):
        r = engine().run(Criteria(), small_df())
        self.assertIsInstance(r, TrendReport)  # built through the strict validators
        self.assertEqual(r.status, "ok")
        self.assertIsNone(r.error)
        self.assertEqual(r.effective_criteria.window_end, "2015-02")  # D2: latest month
        self.assertIsNone(r.criteria_in.window_end)                    # request as received
        self.assertEqual(len(r.records), 12 * 8)
        self.assertEqual(r.coverage_score, 0.0)
        self.assertEqual((r.summary.n_rows, r.summary.price, r.summary.price_per_sqft), (0, None, None))
        m = r.metadata
        self.assertEqual((m.contract_version, m.logic_version, m.snapshot_sha256), ("1.1.0", "abc1234", SNAPSHOT_SHA))
        self.assertEqual((m.topology, m.n_scanners, m.partial_last_month, m.llm_mode, m.llm), ("parallel", 7, True, "off", None))
        self.assertEqual((m.loop_counters.L1_repairs, m.loop_counters.L2_attempts), (0, 0))
        self.assertEqual([e.i for e in r.trace], list(range(len(r.trace))))
        self.assertEqual(r.trace[0].msg, "topology=parallel (7 localities >= 3)")

    def test_output_survives_json_roundtrip(self):
        r = engine().run(Criteria(), small_df())
        text = report_to_json(r)
        self.assertEqual(report_to_json(TrendReport.model_validate_json(text)), text)

    def test_deterministic_bytes(self):  # I-DET
        e, df = engine(), small_df()
        a = report_to_json(e.run(Criteria(localities=["Adyar"]), df, seed=7))
        b = report_to_json(e.run(Criteria(localities=["Adyar"]), df, seed=7))
        self.assertEqual(a, b)

    def test_input_not_modified(self):  # I-PURE
        df, crit = small_df(), Criteria(localities=["Adyar"])
        df0, crit0 = df.copy(deep=True), crit.model_copy(deep=True)
        engine().run(crit, df)
        pd.testing.assert_frame_equal(df, df0)
        self.assertEqual(crit, crit0)

    def test_dense_grid_follows_effective_criteria(self):  # I-DENSE
        r = engine().run(Criteria(localities=["T Nagar", "Adyar"], window_end="2014-12"), small_df())
        keys = {(x.month, x.region_key) for x in r.records}
        self.assertEqual(keys, {(m, g) for m in window_months("2014-12") for g in ("ALL", "Adyar", "T Nagar")})
        self.assertFalse(r.metadata.partial_last_month)
        self.assertEqual(r.records[0].region_key, "ALL")  # month asc, ALL first, then alphabetical
        self.assertEqual([x.region_key for x in r.records[:3]], ["ALL", "Adyar", "T Nagar"])

    def test_topology_rule_and_force(self):
        df, e = small_df(), engine()
        two = e.run(Criteria(localities=["Adyar", "T Nagar"]), df)
        self.assertEqual((two.metadata.topology, two.metadata.n_scanners), ("consolidated", 1))
        three = e.run(Criteria(localities=["Adyar", "T Nagar", "Chrompet"]), df)
        self.assertEqual((three.metadata.topology, three.metadata.n_scanners), ("parallel", 3))
        forced = e.run(Criteria(localities=["Adyar"]), df, options=RunOptions(force_topology="parallel"))
        self.assertEqual((forced.metadata.topology, forced.metadata.n_scanners), ("parallel", 1))

    def test_price_unit_copied(self):
        r = engine().run(Criteria(price_unit="lakh"), small_df())
        self.assertEqual((r.price_unit, r.effective_criteria.price_unit), ("lakh", "lakh"))

    def test_module_entry_point(self):
        with tempfile.TemporaryDirectory() as d:
            _write_snapshot(d, ok=True)
            os.environ["CHENNAI_DATA_DIR"] = d
            from plotline import orchestrator
            orchestrator._default_engine.cache_clear()
            try:
                self.assertEqual(run(Criteria(), small_df()).status, "ok")
            finally:
                del os.environ["CHENNAI_DATA_DIR"]
                orchestrator._default_engine.cache_clear()


class ErrorReports(unittest.TestCase):
    def check(self, r, code):
        self.assertEqual((r.status, r.error.code), ("error", code))
        self.assertEqual((r.records, r.summary, r.coverage_score, r.anomaly_flags, r.diagnostics), ([], None, 0, [], []))
        self.assertTrue(r.trace and r.trace[-1].kind == "error")
        return r

    def test_ai_mode_with_llm_off(self):
        r = self.check(engine().run("rents in Adyar last year", small_df()), "E_LLM_OFF")
        self.assertIsNone(r.criteria_in)

    def test_ai_mode_with_model_on_is_unparseable_in_stub(self):
        self.check(engine(llm_mode="replay").run("rents in Adyar", small_df()), "E_NL_UNPARSEABLE")

    def test_missing_column(self):
        self.check(engine().run(Criteria(), small_df().drop(columns=["price"])), "E_SCHEMA")

    def test_invalid_criteria_is_a_report_not_an_exception(self):
        r = self.check(engine().run(Criteria(price_band=[9, 1]), small_df()), "E_INVALID_CRITERIA")
        self.assertIn("price_band", r.error.message)
        self.assertEqual(r.criteria_in.price_band, [9, 1])  # as received

    def test_window_out_of_range(self):
        r = self.check(engine().run(Criteria(window_end="2012-01"), small_df()), "E_INVALID_CRITERIA")
        self.assertIn("window_end", r.error.message)

    def test_snapshot_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            _write_snapshot(d, ok=False)
            r = Engine.from_data_dir(d, logic_version="abc1234").run(Criteria(), small_df())
            self.check(r, "E_SNAPSHOT_HASH")

    def test_snapshot_hash_match(self):
        with tempfile.TemporaryDirectory() as d:
            _write_snapshot(d, ok=True)
            e = Engine.from_data_dir(d, logic_version="abc1234")
            self.assertIsNone(e.snapshot_error)
            self.assertEqual(e.run(Criteria(), small_df()).status, "ok")


def _write_snapshot(d, ok):
    data = b"listing_id,locality\nP1,Adyar\n"
    Path(d, "chennai_snapshot.csv").write_bytes(data)
    sha = hashlib.sha256(data).hexdigest() if ok else "0" * 64
    Path(d, "SNAPSHOT.sha256").write_text(sha + "\n")


class Loops(unittest.TestCase):
    """The stubs never fire a loop; fake agents prove the orchestrator and trace logger do."""

    def agents(self, **over):
        return replace(stubs.stub_agents(), **over)

    # ---- L1 -------------------------------------------------------------
    def swap_repair(self, plan, request, info, options, l1_repairs, trace):
        lo, hi = plan.effective.price_band
        trace.l1_fired("band_inverted", [lo, hi], [hi, lo], l1_repairs + 1)
        eff = plan.effective.model_copy(update={"price_band": [hi, lo]})
        return replace(plan, effective=eff)

    def test_l1_repair_then_ok(self):
        r = engine(agents=self.agents(repair=self.swap_repair)).run(Criteria(price_band=[9, 1]), small_df())
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.effective_criteria.price_band, [1, 9])
        self.assertEqual(r.criteria_in.price_band, [9, 1])
        loops = [e for e in r.trace if e.kind == "loop"]
        self.assertEqual([(e.loop, e.msg) for e in loops], [("L1", "L1 fired: band_inverted; [9,1] -> [1,9]; repair 1 of 2")])
        self.assertEqual(r.metadata.loop_counters.L1_repairs, 1)

    def test_l1_cap_gives_invalid_criteria(self):
        def never_fixes(plan, request, info, options, l1_repairs, trace):
            trace.l1_fired("band_inverted", [9, 1], [9, 1], l1_repairs + 1)
            return plan
        r = engine(agents=self.agents(repair=never_fixes)).run(Criteria(price_band=[9, 1]), small_df())
        self.assertEqual((r.status, r.error.code), ("error", "E_INVALID_CRITERIA"))
        self.assertEqual(r.metadata.loop_counters.L1_repairs, 2)
        self.assertEqual(sum(e.kind == "loop" for e in r.trace), 2)

    def test_loops_disabled_means_no_repair(self):
        called = []
        def spy(*a, **k): called.append(1)
        r = engine(agents=self.agents(repair=spy)).run(
            Criteria(price_band=[9, 1]), small_df(), options=RunOptions(loops_enabled=False))
        self.assertEqual((r.status, r.error.code), ("error", "E_INVALID_CRITERIA"))
        self.assertEqual((called, r.metadata.loops_enabled, r.metadata.loop_counters.L1_repairs), ([], False, 0))

    def test_repair_failure_is_reported(self):
        def cannot(plan, request, info, options, l1_repairs, trace):
            from plotline.contract import ErrorInfo
            return Failure(ErrorInfo(code="E_INVALID_CRITERIA", message="invalid localities: no close match"))
        r = engine(agents=self.agents(repair=cannot)).run(Criteria(localities=["Xyz"]), small_df())
        self.assertEqual((r.error.code, r.error.message), ("E_INVALID_CRITERIA", "invalid localities: no close match"))

    # ---- L2 -------------------------------------------------------------
    def widening_validate(self, max_attempts):
        bands = [[6600000, 9400000], [6000000, 10000000]]  # golden.md A3
        def validate(records, effective, original, options, l2_attempts, llm_mode, seed, trace, llm=None):
            if l2_attempts < max_attempts:
                band = bands[l2_attempts] if l2_attempts < 2 else None
                if l2_attempts < 3:  # the trace logger itself refuses a 4th firing
                    trace.l2_fired(3, l2_attempts + 1, band)
                wide = effective.model_copy(update={"price_band": band})
                return CoverageDecision(3, 3 / 12, widen_to=wide)
            return CoverageDecision(0, 0.0)  # the stub scanner returns no rows, so the final coverage is 0
        return validate

    def test_l2_two_attempts_like_golden_a3(self):
        crit = Criteria(localities=["Adyar"], bhk=[1], price_band=[7000000, 9000000], window_end="2014-12")
        r = engine(agents=self.agents(validate=self.widening_validate(2))).run(crit, small_df())
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.effective_criteria.price_band, [6000000, 10000000])
        self.assertEqual(r.criteria_in.price_band, [7000000, 9000000])
        msgs = [e.msg for e in r.trace if e.kind == "loop"]
        self.assertEqual(msgs, [
            "L2 fired: coverage 3/12 below 9/12; widen soft ranges by 20%; attempt 1 of 3",
            "L2 fired: coverage 3/12 below 9/12; widen soft ranges by 50%; attempt 2 of 3",
        ])
        self.assertEqual(r.metadata.loop_counters.L2_attempts, 2)

    def test_l2_cap_is_hard(self):
        crit = Criteria(price_band=[7000000, 9000000])
        with self.assertRaises(RuntimeError):  # a validator asking for a 4th attempt is a bug
            engine(agents=self.agents(validate=self.widening_validate(99))).run(crit, small_df())

    def test_unlogged_loop_firing_is_a_bug(self):  # I-CAP
        def silent(records, effective, original, options, l2_attempts, llm_mode, seed, trace, llm=None):
            return CoverageDecision(3, 0.25, widen_to=effective.model_copy(update={"price_band": None})) if l2_attempts == 0 else CoverageDecision(0, 0.0)
        with self.assertRaises(RuntimeError):
            engine(agents=self.agents(validate=silent)).run(Criteria(), small_df())

    def test_l2_never_triggers_l1(self):
        calls = {"n": 0}
        def agg(effective, rows, df, info, trace):
            calls["n"] += 1
            return L1Request(["band_inverted"], ["price_band"]) if calls["n"] == 2 else stubs.aggregate(effective, rows, df, info, trace)
        with self.assertRaises(RuntimeError):
            engine(agents=self.agents(aggregate=agg, validate=self.widening_validate(1))).run(
                Criteria(price_band=[7000000, 9000000]), small_df())

    def test_validator_skip_and_disabled_are_not_firings(self):
        r = engine().run(Criteria(), small_df())  # no soft filters, low coverage
        self.assertIn("L2 skipped: nothing to widen", [e.msg for e in r.trace])
        self.assertEqual(r.metadata.loop_counters.L2_attempts, 0)
        r = engine().run(Criteria(), small_df(), options=RunOptions(loops_enabled=False))
        self.assertIn("L2 disabled", [e.msg for e in r.trace])

    # ---- later agents ---------------------------------------------------
    def test_diagnostic_replay_miss_fails_the_report(self):
        from plotline.contract import ErrorInfo
        def miss(flags, records, llm_mode, seed, trace):
            return Failure(ErrorInfo(code="E_REPLAY_MISS", message="not in cache"))
        r = engine(agents=self.agents(diagnose=miss)).run(Criteria(), small_df())
        self.assertEqual((r.status, r.error.code), ("error", "E_REPLAY_MISS"))
        self.assertEqual(r.trace[-1].agent, "diagnostic")


@unittest.skipUnless(os.environ.get("CHENNAI_RAW_CSV"), "set CHENNAI_RAW_CSV to the raw Kaggle file")
class RealData(unittest.TestCase):
    def test_default_window_is_latest_month_of_real_data(self):
        raw = pd.read_csv(os.environ["CHENNAI_RAW_CSV"])
        raw = raw.dropna(subset=["N_BEDROOM"])
        df = pd.DataFrame({
            "listing_id": raw["PRT_ID"], "locality": raw["AREA"].str.strip(), "sqft": raw["INT_SQFT"],
            "sale_date": pd.to_datetime(raw["DATE_SALE"], format="%d-%m-%Y").dt.strftime("%Y-%m-%d"),
            "bhk": raw["N_BEDROOM"].astype(int), "sale_cond": raw["SALE_COND"].str.strip(), "price": raw["SALES_PRICE"],
        })
        r = engine().run(Criteria(), df)
        self.assertEqual((r.status, r.effective_criteria.window_end, r.metadata.partial_last_month), ("ok", "2015-02", True))
        self.assertEqual((r.records[0].month, r.records[-1].month), ("2014-03", "2015-02"))
        self.assertEqual(engine().run(Criteria(window_end="2004-12"), df).effective_criteria.window_end, "2004-12")
        self.assertEqual(engine().run(Criteria(window_end="2004-11"), df).error.code, "E_INVALID_CRITERIA")


if __name__ == "__main__":
    unittest.main()
