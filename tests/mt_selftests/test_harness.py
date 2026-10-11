"""Harness self-tests (contracts/Testing.md 11, T22): dummy MRs end to end."""

import csv
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from plotline.contract import Criteria, canonical_criteria_json
from plotline.orchestrator import Engine
from tests.mt.generator import Base
from tests.mt.harness import (
    MR,
    VIOLATION_COLUMNS,
    Diff,
    FollowUp,
    HarnessError,
    SeedRegistry,
    abs_tol,
    bit_exact,
    diff,
    keyed,
    oracle_diffs,
    rel_tol,
    report_dict,
    run_mr,
    write_violations,
)
from tests.support import SNAPSHOT_SHA

ENGINE = Engine(SNAPSHOT_SHA, logic_version="abc1234")
RUN = ENGINE.run


def frame() -> pd.DataFrame:
    """Six sales a month in Adyar and T Nagar over 2014-03 .. 2015-02 (full coverage)."""
    rows = []
    for i, m in enumerate(pd.period_range("2014-03", "2015-02", freq="M").astype(str)):
        for j in range(6):
            loc = "Adyar" if j % 2 else "T Nagar"
            rows.append(dict(listing_id=f"P{i}-{j}", locality=loc, sqft=1000 + 10 * j, sale_date=f"{m}-1{j}",
                             bhk=1 + j % 2, sale_cond="Normal Sale", price=5_000_000 + 100_000 * (i + j)))
    return pd.DataFrame(rows)


def base(base_id: int, **criteria) -> Base:
    c = Criteria(window_end="2015-02", **criteria)
    return Base(base_id, "broad", 0, c.model_dump(mode="json"), canonical_criteria_json(c), {"MR1": {"permutation_seed": 7}})


BASES = [base(0), base(1, localities=["Adyar"]), base(2, bhk=[1])]


def whole_report(src: dict, fu: dict, b: Base) -> list[Diff]:
    strip = lambda d: keyed({k: v for k, v in d.items() if k not in ("trace", "diagnostics", "metadata")})
    return diff(strip(src), strip(fu), bit_exact)


def copy_frame(b: Base, df: pd.DataFrame) -> FollowUp:
    return FollowUp(b.to_criteria(), df.copy())


IDENTITY = MR("dummy-identity", "invariance", copy_frame, whole_report)


class EndToEnd(unittest.TestCase):
    def test_dummy_mr_passes_with_seeds_recorded(self):
        reg = SeedRegistry()
        shuffle = MR("dummy-shuffle", "invariance",
                     lambda b, df: FollowUp(b.to_criteria(), df.sample(frac=1, random_state=b.params["MR1"]["permutation_seed"]),
                                            seeds={"permutation": b.params["MR1"]["permutation_seed"]}),
                     whole_report)
        run = run_mr(shuffle, BASES, frame(), RUN, seeds=(0, 5), registry=reg, check_oracle=True)
        self.assertEqual([p.outcome for p in run.pairs], ["pass"] * 6)
        self.assertEqual((run.invariant_violations, run.oracle_mismatches), ([], []))
        self.assertEqual(reg.seeds("run"), [0, 5, 0, 5, 0, 5])
        self.assertEqual(reg.seeds("dummy-shuffle permutation"), [7] * 6)
        r = run.result()
        self.assertEqual((r.n_bases, r.evaluated, r.violations, r.pairs, r.pair_violations), (3, 3, 0, 6, 0))

    def test_violation_names_its_field(self):
        drop_first = MR("dummy-drop", "invariance", lambda b, df: FollowUp(b.to_criteria(), df.iloc[1:].copy()),
                        whole_report)
        run = run_mr(drop_first, BASES[:1], frame(), RUN)
        self.assertEqual(run.pairs[0].outcome, "violation")
        fields = {row["field"] for row in run.violation_rows()}
        self.assertIn("records.2014-03/ALL.listing_count", fields)
        self.assertIn("summary.n_rows", fields)
        with tempfile.TemporaryDirectory() as d:
            path = write_violations(run.violation_rows(), Path(d) / "violations.csv")
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(tuple(rows[0]), VIOLATION_COLUMNS)
            self.assertEqual((rows[0]["MR"], rows[0]["base_id"], rows[0]["seed"]), ("dummy-drop", "0", "0"))

    def test_any_seed_rule(self):
        def seed_sensitive(src, fu, b):  # violates on seed 5 only (pretend)
            return [Diff("x", 0, 1)] if fu["metadata"]["seed"] == 5 else []
        run = run_mr(MR("dummy-seed", "invariance", copy_frame, seed_sensitive), BASES[:2], frame(), RUN, seeds=(0, 5))
        r = run.result()
        self.assertEqual((r.violations, r.pairs, r.pair_violations), (2, 4, 2))


class SkipsAndErrors(unittest.TestCase):
    def test_skip_is_logged_not_passed_and_waived_when_unconditioned(self):
        def always_differs(src, fu, b):
            return [Diff("y", 1, 2)]
        mr = MR("dummy-skip", "monotonic", copy_frame, always_differs,
                precondition=lambda b: "no localities" if b.criteria["localities"] is None else None,
                skip=lambda src, fu, b: "bhk set" if b.criteria["bhk"] else None)
        bases = [base(0), base(1, localities=["Adyar"]), base(2, localities=["T Nagar"], bhk=[1])]
        run = run_mr(mr, bases, frame(), RUN, check_invariants=False)
        self.assertEqual([p.outcome for p in run.pairs], ["skip", "violation", "skip"])
        self.assertEqual([s["reason"] for s in run.skip_rows()], ["precondition: no localities", "bhk set"])
        r = run.result()
        self.assertEqual((r.evaluated, r.violations, r.skipped), (1, 1, {"precondition: no localities": 1, "bhk set": 1}))
        self.assertEqual(r.unconditioned, (2, 2))  # the report-field skip is waived, the precondition is not

    def test_follow_up_error_is_a_status_violation(self):
        mr = MR("dummy-error", "invariance", lambda b, df: FollowUp(Criteria(localities=["Mumbai"]), df.copy()),
                whole_report, skip=lambda src, fu, b: "never applies to errors")
        run = run_mr(mr, BASES[:1], frame(), RUN)
        self.assertEqual((run.pairs[0].outcome, run.pairs[0].diffs), ("violation", [Diff("status", "ok", "error")]))

    def test_source_error_stops_the_run(self):
        with self.assertRaises(HarnessError):
            run_mr(IDENTITY, [base(9, localities=["Mumbai"])], frame(), RUN)

    def test_transformation_must_not_reuse_or_modify_the_source(self):
        same = MR("dummy-same", "invariance", lambda b, df: FollowUp(b.to_criteria(), df), whole_report)
        with self.assertRaises(HarnessError):
            run_mr(same, BASES[:1], frame(), RUN)

        def mutate(b, df):
            df.loc[df.index[0], "price"] = 1
            return FollowUp(b.to_criteria(), df.copy())
        with self.assertRaises(HarnessError):
            run_mr(MR("dummy-mutate", "invariance", mutate, whole_report), BASES[:1], frame(), RUN)

    def test_invariant_checks_catch_nondeterminism(self):
        calls = {"n": 0}

        def flaky(query, df, seed, options):
            calls["n"] += 1
            return RUN(query, df, seed + calls["n"] % 2, options)  # seed differs between the two source runs
        run = run_mr(IDENTITY, BASES[:1], frame(), flaky)
        self.assertEqual([v["invariant"] for v in run.invariant_violations], ["I-DET"])


class Comparators(unittest.TestCase):
    def test_null_only_equals_null(self):
        for cmp in (rel_tol, abs_tol, bit_exact):
            self.assertTrue(cmp(None, None))
            self.assertFalse(cmp(None, 0.0))

    def test_tolerances(self):
        self.assertTrue(rel_tol(1e6, 1e6 * (1 + 5e-10)))
        self.assertFalse(rel_tol(1e6, 1e6 * (1 + 5e-9)))
        self.assertTrue(abs_tol(0.1, 0.1 + 5e-10))
        self.assertFalse(bit_exact(0.1 + 0.2, 0.3))
        self.assertFalse(bit_exact(1, 1.0))

    def test_oracle_check(self):
        df = frame()
        d = report_dict(RUN(Criteria(window_end="2015-02"), df, 0))
        self.assertEqual(oracle_diffs(d, df), [])
        d["records"][0]["median_price"] *= 1.01
        self.assertEqual([x.field for x in oracle_diffs(d, df)], ["records.2014-03/ALL.median_price"])


if __name__ == "__main__":
    unittest.main()
