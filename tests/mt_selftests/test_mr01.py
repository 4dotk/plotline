"""MR1 (shuffle rows): the transformation, a small real run, and a planted fault it must catch."""

import unittest
from dataclasses import replace

import pandas as pd

from plotline.agents import aggregator, default_agents
from plotline.orchestrator import Engine
from tests.mt.generator import SNAPSHOT, generate
from tests.mt.harness import SeedRegistry, frame_hash, run_mr
from tests.mt.mrs import MR1
from tests.support import SNAPSHOT_SHA


def first_row_median(effective, rows, df, info, trace):
    """A planted I-ORDER fault: the ALL median price is the bucket's first row, not its median."""
    out = aggregator.aggregate(effective, rows, df, info, trace)
    if not isinstance(out, list):
        return out
    first = rows.assign(month=rows["sale_date"].str[:7]).groupby("month", sort=False)["price"].first()
    return [r.model_copy(update={"median_price": float(first[r.month])})
            if r.region_key == "ALL" and r.n_in_bucket and r.month in first else r for r in out]


@unittest.skipUnless(SNAPSHOT.is_file(), "frozen snapshot not present")
class MR1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(SNAPSHOT)
        cls.bases = generate(cls.df, 12)
        cls.engine = Engine(SNAPSHOT_SHA, logic_version="abc1234")

    def test_transformation_is_a_seeded_permutation(self):
        b = self.bases[0]
        h = frame_hash(self.df)
        fu = MR1.transform(b, self.df)
        self.assertEqual(frame_hash(self.df), h)  # source untouched (I-PURE)
        self.assertIsNot(fu.df, self.df)
        self.assertNotEqual(list(fu.df["listing_id"][:20]), list(self.df["listing_id"][:20]))
        cols = list(self.df.columns)
        pd.testing.assert_frame_equal(fu.df.sort_values(cols).reset_index(drop=True),
                                      self.df.sort_values(cols).reset_index(drop=True))  # same multiset
        self.assertEqual(fu.seeds, {"permutation": b.params["MR1"]["permutation_seed"]})
        pd.testing.assert_frame_equal(MR1.transform(b, self.df).df, fu.df)  # same seed, same order

    def test_application_passes_and_matches_the_oracle(self):
        reg = SeedRegistry()
        run = run_mr(MR1, self.bases, self.df, self.engine.run, registry=reg, check_oracle=True)
        r = run.result()
        self.assertEqual((r.evaluated, r.violations, r.n_skipped), (12, 0, 0))
        self.assertEqual((run.invariant_violations, run.oracle_mismatches), ([], []))
        self.assertEqual(len(reg.seeds("MR1 permutation")), 12)

    def test_catches_an_order_dependent_fault(self):
        faulty = Engine(SNAPSHOT_SHA, logic_version="abc1234",
                        agents=replace(default_agents(), aggregate=first_row_median))
        run = run_mr(MR1, self.bases, self.df, faulty.run, check_invariants=False)
        self.assertGreater(run.result().violations, len(self.bases) // 2)
        fields = {row["field"] for row in run.violation_rows()}
        self.assertTrue(any(f.endswith("/ALL.median_price") for f in fields), sorted(fields)[:5])


if __name__ == "__main__":
    unittest.main()
