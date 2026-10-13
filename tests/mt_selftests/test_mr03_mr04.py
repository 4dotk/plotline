"""MR3a / MR3b (duplicate rows) and MR4 (add X to one month): transformations, skips, planted faults."""

import unittest
from dataclasses import replace

import pandas as pd

from plotline.agents import default_agents, scanner
from plotline.contract import MIN_BUCKET_N, month_add, window_months
from plotline.orchestrator import Engine
from tests.mt.generator import SNAPSHOT, generate
from tests.mt.harness import frame_hash, run_mr
from tests.mt.mrs import MR3a, MR3b, MR4
from tests.mt.mrs.mr03_duplicate import gate_skip
from tests.support import SNAPSHOT_SHA

LEAK_FROM_DAY = "28"  # planted fault parameter: sales from this day on land in the next month


def dedup_by_id(plan, df, trace):
    """Planted D3 fault: rows with a repeated ``listing_id`` are dropped."""
    return scanner.scan(plan, df, trace).drop_duplicates("listing_id")


def month_end_leak(plan, df, trace):
    """Planted bucket-leak fault: late-month sales are counted in the next month."""
    rows = scanner.scan(plan, df, trace)
    late = rows["sale_date"].str.slice(8, 10) >= LEAK_FROM_DAY
    nxt = rows["sale_date"].str.slice(0, 7).map(lambda m: month_add(m, 1) + "-01")
    return rows.assign(sale_date=rows["sale_date"].where(~late, nxt))


def series(counts):
    """A hand-built report fragment: an ALL series with these ``n_in_bucket`` values."""
    return {"records": [{"month": m, "region_key": "ALL", "n_in_bucket": n}
                        for m, n in zip(window_months("2010-12"), counts)]}


@unittest.skipUnless(SNAPSHOT.is_file(), "frozen snapshot not present")
class MR3MR4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(SNAPSHOT)
        cls.bases = generate(cls.df, 16)
        cls.engine = Engine(SNAPSHOT_SHA, logic_version="abc1234")

    def faulty(self, **agents):
        return Engine(SNAPSHOT_SHA, logic_version="abc1234", agents=replace(default_agents(), **agents)).run

    def test_mr3_transformations(self):
        h = frame_hash(self.df)
        a, b = MR3a.transform(self.bases[0], self.df).df, MR3b.transform(self.bases[0], self.df).df
        self.assertEqual(frame_hash(self.df), h)
        self.assertEqual((len(a), len(b)), (2 * len(self.df), 2 * len(self.df)))
        self.assertEqual(a["listing_id"].nunique(), 2 * self.df["listing_id"].nunique())
        self.assertTrue(a["listing_id"].str.endswith("_dup").sum() == len(self.df))
        self.assertEqual(b["listing_id"].nunique(), self.df["listing_id"].nunique())

    def test_mr3_gate_skip(self):
        big = 2 * MIN_BUCKET_N
        self.assertIsNone(gate_skip(series([big] * 12)))
        self.assertIsNotNone(gate_skip(series([big] * 5 + [MIN_BUCKET_N - 1] + [big] * 6)))  # one ALL month
        self.assertIsNotNone(gate_skip(series([1, 1, 1] + [big] * 9)))  # pooled first-3 = 3

    def test_mr4_transformation(self):
        base = self.bases[0]
        x, m = base.params["MR4"]["X"], base.params["MR4"]["month"]
        fu = MR4.transform(base, self.df).df
        in_m = self.df["sale_date"].str.slice(0, 7) == m
        self.assertTrue(in_m.any())
        pd.testing.assert_series_equal(fu["price"][in_m], self.df["price"][in_m] + x)
        pd.testing.assert_series_equal(fu["price"][~in_m], self.df["price"][~in_m])

    def test_application_passes(self):
        for mr in (MR3a, MR3b, MR4):
            run = run_mr(mr, self.bases, self.df, self.engine.run, check_oracle=True)
            r = run.result()
            self.assertGreater(r.evaluated, 0, r.skipped)
            self.assertEqual((run.invariant_violations, run.oracle_mismatches), ([], []))
            self.assertEqual(r.violations, 0, run.violation_rows()[:3])

    def test_mr3b_catches_dedup_and_mr3a_does_not(self):
        faulty = self.faulty(scan=dedup_by_id)
        b = run_mr(MR3b, self.bases, self.df, faulty, check_invariants=False)
        a = run_mr(MR3a, self.bases, self.df, faulty, check_invariants=False)
        self.assertEqual(b.result().violations, b.result().evaluated)
        self.assertTrue(any(row["field"].endswith(".listing_count") for row in b.violation_rows()))
        self.assertEqual(a.result().violations, 0)

    def test_mr4_catches_a_bucket_leak(self):
        run = run_mr(MR4, self.bases, self.df, self.faulty(scan=month_end_leak), check_invariants=False)
        self.assertGreater(run.result().violations, 0)
        self.assertTrue(any(row["field"].endswith(".median_price") for row in run.violation_rows()))


if __name__ == "__main__":
    unittest.main()
