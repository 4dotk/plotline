"""MR11 (repair invariance): the transformation, a real run that passes, and planted repair faults it must catch."""

import unittest
from unittest import mock

import pandas as pd

from plotline.agents import planner
from plotline.orchestrator import Engine
from tests.mt.generator import SNAPSHOT, generate
from tests.mt.harness import frame_hash, run_mr
from tests.mt.mrs import MR11
from tests.support import SNAPSHOT_SHA

_REPAIR = planner._repair_one


def band_not_swapped(issue, eff, info):
    return list(eff.price_band) if issue == "band_inverted" else _REPAIR(issue, eff, info)


def wrong_locality(issue, eff, info):
    return ["Velachery" for _ in eff.localities] if issue == "locality_unknown" else _REPAIR(issue, eff, info)


@unittest.skipUnless(SNAPSHOT.is_file(), "frozen snapshot not present")
class MR11Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(SNAPSHOT)
        cls.bases = generate(cls.df, 12)
        cls.engine = Engine(SNAPSHOT_SHA, logic_version="abc1234")

    def outcomes(self):
        return [p.outcome for p in run_mr(MR11, self.bases, self.df, self.engine.run, (0,), check_invariants=False).pairs]

    def test_transformation_plants_every_defect_and_keeps_the_source(self):
        b = next(b for b in self.bases if b.criteria["price_band"] and b.criteria["localities"])
        h = frame_hash(self.df)
        fu = MR11.transform(b, self.df)
        self.assertEqual(frame_hash(self.df), h)  # I-PURE
        self.assertEqual(fu.query.price_band, list(reversed(b.criteria["price_band"])))
        self.assertTrue(all(name != name.strip() for name in fu.query.localities))
        self.assertEqual(fu.query.domain_violations()[:1], ["band_inverted"])

    def test_the_real_application_passes_with_one_repair(self):
        out = self.outcomes()
        self.assertNotIn("violation", out)
        self.assertGreater(out.count("pass"), 0)

    def test_a_band_that_is_not_swapped_is_caught(self):
        with mock.patch.object(planner, "_repair_one", band_not_swapped):
            self.assertIn("violation", self.outcomes())

    def test_a_locality_repaired_to_the_wrong_place_is_caught(self):
        with mock.patch.object(planner, "_repair_one", wrong_locality):
            self.assertIn("violation", self.outcomes())


if __name__ == "__main__":
    unittest.main()
