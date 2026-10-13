"""MR2 (unit change) and MR8 (scale prices by k): transformations, skip rule, planted faults."""

import unittest
from dataclasses import replace

import pandas as pd

from plotline.agents import aggregator, default_agents, scanner
from plotline.contract import ANOMALY_PCT
from plotline.orchestrator import Engine
from tests.mt.generator import SNAPSHOT, generate
from tests.mt.harness import frame_hash, run_mr
from tests.mt.mrs import MR2, MR8
from tests.mt.mrs.common import flag_margin
from tests.mt.mrs.mr02_unit_change import INR_PER_LAKH
from tests.support import SNAPSHOT_SHA

# Planted fault parameter (not a test tolerance): an absolute "too cheap to be real" price in INR.
PLANTED_MIN_PRICE = 10_000_000


def whole_rupee_medians(effective, rows, df, info, trace):
    """Planted unit fault: medians rounded to whole rupees, as if prices were always INR."""
    out = aggregator.aggregate(effective, rows, df, info, trace)
    if not isinstance(out, list):
        return out
    return [r.model_copy(update={"median_price": None if r.median_price is None else float(round(r.median_price))})
            for r in out]


def absolute_floor(plan, df, trace):
    """Planted threshold fault: rows under a fixed INR price are dropped as implausible."""
    rows = scanner.scan(plan, df, trace)
    return rows[rows["price"] >= PLANTED_MIN_PRICE]


def report(pcts):
    """A hand-built report fragment with an ALL series carrying these pct changes."""
    return {"records": [{"month": f"2010-{i + 1:02d}", "region_key": "ALL", "pct_change_price_per_sqft": p}
                        for i, p in enumerate(pcts)]}


@unittest.skipUnless(SNAPSHOT.is_file(), "frozen snapshot not present")
class MR2MR8Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(SNAPSHOT)
        cls.bases = generate(cls.df, 12)
        cls.band = next(b for b in cls.bases if b.criteria["price_band"] is not None)
        cls.engine = Engine(SNAPSHOT_SHA, logic_version="abc1234")

    def test_mr2_transformation(self):
        h = frame_hash(self.df)
        fu = MR2.transform(self.band, self.df)
        self.assertEqual(frame_hash(self.df), h)  # source untouched (I-PURE)
        self.assertIsNot(fu.df, self.df)
        pd.testing.assert_series_equal(fu.df["price"], self.df["price"] / INR_PER_LAKH)
        self.assertEqual(fu.query.price_unit, "lakh")
        self.assertEqual(fu.query.price_band, [v / INR_PER_LAKH for v in self.band.criteria["price_band"]])
        self.assertEqual(self.band.criteria["price_unit"], "inr")  # base criteria untouched

    def test_mr8_transformation(self):
        k = self.band.params["MR8"]["k"]
        fu = MR8.transform(self.band, self.df)
        self.assertIsNot(fu.df, self.df)
        pd.testing.assert_series_equal(fu.df["price"], self.df["price"] * k)
        self.assertEqual(fu.query.price_band, [v * k for v in self.band.criteria["price_band"]])
        self.assertEqual(fu.query.price_unit, "inr")

    def test_flag_margin_skip(self):
        self.assertIsNone(flag_margin(report([None, 0.05, -0.2])))
        self.assertIsNotNone(flag_margin(report([None, ANOMALY_PCT])))
        self.assertIsNotNone(flag_margin(report([None, -ANOMALY_PCT])))  # |pct|, both signs
        fake = report([None, ANOMALY_PCT])
        self.assertIsNotNone(MR2.skip({"records": []} | report([None]), fake, self.band))  # follow-up checked too

    def test_application_passes(self):
        for mr in (MR2, MR8):
            run = run_mr(mr, self.bases, self.df, self.engine.run, check_oracle=True)
            r = run.result()
            self.assertEqual(r.evaluated + r.n_skipped, len(self.bases))
            self.assertEqual((run.invariant_violations, run.oracle_mismatches), ([], []))
            self.assertEqual(r.violations, 0, run.violation_rows()[:3])

    def test_mr2_catches_a_unit_fault(self):
        faulty = Engine(SNAPSHOT_SHA, logic_version="abc1234",
                        agents=replace(default_agents(), aggregate=whole_rupee_medians))
        run = run_mr(MR2, self.bases, self.df, faulty.run, check_invariants=False)
        self.assertGreater(run.result().violations, len(self.bases) // 2)
        self.assertTrue(any(row["field"].endswith(".median_price") for row in run.violation_rows()))

    def test_mr8_catches_an_absolute_threshold(self):
        faulty = Engine(SNAPSHOT_SHA, logic_version="abc1234",
                        agents=replace(default_agents(), scan=absolute_floor))
        run = run_mr(MR8, self.bases, self.df, faulty.run, check_invariants=False)
        self.assertGreater(run.result().violations, len(self.bases) // 2)
        self.assertTrue(any(row["field"].endswith(".n_in_bucket") for row in run.violation_rows()))


if __name__ == "__main__":
    unittest.main()
