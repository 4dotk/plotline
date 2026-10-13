"""MR5 (widen band), MR6 (sub-region), MR7 (window + 1): transformations, preconditions, planted faults."""

import unittest
from dataclasses import replace

import pandas as pd

from plotline.agents import default_agents, scanner
from plotline.contract import Criteria, month_add
from plotline.orchestrator import Engine
from tests.mt.generator import SNAPSHOT, Base, generate, valid_window_ends
from tests.mt.harness import frame_hash, run_mr
from tests.mt.mrs import MR5, MR6, MR7
from tests.support import SNAPSHOT_SHA

# Planted fault parameters (not test tolerances)
WIDE_BAND_CAP = 8_000_000  # a band wider than this (INR) is "a typo" and gets cut to this width
TRIM_QUANTILE = 0.9  # rows priced above this window quantile are dropped as outliers


def first_locality_twice(plan, df, trace):
    """Planted merge fault: the parallel topology counts the first locality's rows twice."""
    rows = scanner.scan(plan, df, trace)
    if plan.topology != "parallel" or rows.empty:
        return rows
    return pd.concat([rows, rows[rows["locality"] == rows["locality"].min()]], ignore_index=True)


def window_trim(plan, df, trace):
    """Planted window-wide state: outliers are judged against the whole window."""
    rows = scanner.scan(plan, df, trace)
    return rows[rows["price"] <= rows["price"].quantile(TRIM_QUANTILE)] if len(rows) else rows


@unittest.skipUnless(SNAPSHOT.is_file(), "frozen snapshot not present")
class MR5toMR7Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(SNAPSHOT)
        cls.bases = generate(cls.df, 40)
        cls.engine = Engine(SNAPSHOT_SHA, logic_version="abc1234")

    def faulty(self, **agents):
        return Engine(SNAPSHOT_SHA, logic_version="abc1234", agents=replace(default_agents(), **agents)).run

    def test_transformations_keep_the_source(self):
        h = frame_hash(self.df)
        for mr in (MR5, MR6, MR7):
            for b in self.bases:
                if mr.precondition(b, self.df) is None:
                    before = dict(b.criteria)
                    fu = mr.transform(b, self.df)
                    self.assertIsNot(fu.df, self.df)
                    self.assertEqual(b.criteria, before)  # base criteria untouched
        self.assertEqual(frame_hash(self.df), h)

    def test_mr5_widens_by_delta(self):
        b = next(b for b in self.bases if b.criteria["price_band"] is not None)
        lo, hi = b.criteria["price_band"]
        d = b.params["MR5"]["delta"]
        flo, fhi = MR5.transform(b, self.df).query.price_band
        self.assertAlmostEqual(lo - flo, d * (hi - lo))
        self.assertAlmostEqual(fhi - hi, d * (hi - lo))

    def test_mr6_subset_is_proper(self):
        for b in self.bases:
            s = b.params["MR6"]["subset"]
            if s is not None:
                self.assertLess(set(s), set(b.criteria["localities"]))
                self.assertEqual(MR6.transform(b, self.df).query.localities, s)

    def test_preconditions(self):
        no_band = next(b for b in self.bases if b.criteria["price_band"] is None)
        self.assertIsNotNone(MR5.precondition(no_band, self.df))
        one = next(b for b in self.bases if b.params["MR6"]["subset"] is None)
        self.assertIsNotNone(MR6.precondition(one, self.df))
        last = replace(self.bases[0], criteria={**self.bases[0].criteria, "window_end": valid_window_ends(self.df)[-1]})
        self.assertIsNotNone(MR7.precondition(last, self.df))
        self.assertIsNone(MR7.precondition(replace(last, criteria={**last.criteria,
                          "window_end": month_add(last.criteria["window_end"], -1)}), self.df))

    def test_application_passes(self):
        for mr in (MR5, MR6, MR7):
            run = run_mr(mr, self.bases, self.df, self.engine.run, check_oracle=True)
            r = run.result()
            self.assertGreater(r.evaluated, 0, r.skipped)
            self.assertEqual((run.invariant_violations, run.oracle_mismatches), ([], []))
            self.assertEqual(r.violations, 0, run.violation_rows()[:3])

    def test_mr5_catches_a_band_cap(self):
        def capped(query, df, seed, options):
            band = query.price_band
            if band is not None and band[1] - band[0] > WIDE_BAND_CAP:
                query = Criteria.model_validate({**query.model_dump(), "price_band": [band[0], band[0] + WIDE_BAND_CAP]})
            return self.engine.run(query, df, seed, options)

        run = run_mr(MR5, self.bases, self.df, capped, check_invariants=False)
        self.assertGreater(run.result().violations, 0)
        self.assertTrue(all(row["field"].endswith(".listing_count") for row in run.violation_rows()))

    def test_mr6_catches_a_parallel_double_count(self):
        run = run_mr(MR6, self.bases, self.df, self.faulty(scan=first_locality_twice), check_invariants=False)
        self.assertGreater(run.result().violations, 0)
        self.assertTrue(any(row["field"].endswith(".listing_count") for row in run.violation_rows()))

    def test_mr7_catches_window_wide_state(self):
        run = run_mr(MR7, self.bases, self.df, self.faulty(scan=window_trim), check_invariants=False)
        self.assertGreater(run.result().violations, run.result().evaluated // 2)


if __name__ == "__main__":
    unittest.main()
