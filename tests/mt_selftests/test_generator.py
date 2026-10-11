"""Generator self-tests (contracts/Testing.md 11, T25)."""

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from plotline.contract import GEN_SEED, window_months
from tests.mt.generator import (
    BROAD_MIN_ROWS,
    MIN_BHK_SALES,
    MIN_LOCALITY_SALES,
    SNAPSHOT,
    THIN_ROWS,
    generate,
    load_bases,
    save_bases,
    valid_window_ends,
)
from tests.mt.oracle import matching_rows


@unittest.skipUnless(SNAPSHOT.is_file(), "frozen snapshot not present")
class Generator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(SNAPSHOT)
        cls.bases = generate(cls.df, 100)

    def test_valid_window_ends_from_the_data(self):
        ends = valid_window_ends(self.df)
        self.assertEqual((len(ends), ends[0], ends[-1]), (123, "2004-12", "2015-02"))

    def test_same_seed_same_bases_and_params(self):
        again = generate(self.df, 100)
        self.assertEqual([(b.canonical, b.params) for b in again], [(b.canonical, b.params) for b in self.bases])
        other = generate(self.df, 20, seed=GEN_SEED + 1)
        self.assertNotEqual([b.canonical for b in other], [b.canonical for b in self.bases[:20]])

    def test_distinct_bases_and_ids(self):
        self.assertEqual(len({b.canonical for b in self.bases}), 100)
        self.assertEqual([b.base_id for b in self.bases], list(range(100)))

    def test_strata_and_mix(self):
        self.assertEqual(sum(b.stratum == "thin" for b in self.bases), 20)
        for b in self.bases:
            n = len(matching_rows(self.df, b.criteria))
            self.assertEqual(n, b.n_rows)
            if b.stratum == "broad":
                self.assertGreaterEqual(n, BROAD_MIN_ROWS)
            else:
                self.assertTrue(THIN_ROWS[0] <= n <= THIN_ROWS[1] and b.criteria["price_band"] is not None)

    def test_draw_rules(self):
        months = self.df["sale_date"].str[:7]
        for b in self.bases:
            c = b.criteria
            self.assertIsNotNone(c["window_end"])  # never the default
            self.assertEqual((c["sqft_range"], c["sale_cond"], c["price_unit"]), (None, None, "inr"))
            win = self.df[months.isin(window_months(c["window_end"]))]
            for loc in c["localities"]:
                self.assertGreaterEqual((win["locality"] == loc).sum(), MIN_LOCALITY_SALES)
            if c["bhk"] is not None:
                self.assertIn(len(c["bhk"]), (1, 2))
                pool = win[win["locality"].isin(c["localities"])]
                for v in c["bhk"]:
                    self.assertGreaterEqual((pool["bhk"] == v).sum(), MIN_BHK_SALES)
            if c["price_band"] is not None:
                lo, hi = c["price_band"]
                self.assertLessEqual(lo, hi)

    def test_params(self):
        for b in self.bases:
            p, c = b.params, b.criteria
            self.assertIn(p["MR4"]["month"], window_months(c["window_end"]))
            self.assertIn(p["MR4"]["X"], (250_000, 1_000_000))
            self.assertIn(p["MR5"]["delta"], (0.1, 0.3))
            self.assertIn(p["MR8"]["k"], (2, 4, 10))
            s = p["MR6"]["subset"]
            if len(c["localities"]) < 2:
                self.assertIsNone(s)
            else:
                self.assertTrue(0 < len(s) < len(c["localities"]) and set(s) < set(c["localities"]))

    def test_saved_with_the_seed(self):
        with tempfile.TemporaryDirectory() as d:
            path = save_bases(self.bases, Path(d) / "bases.json", snapshot_sha256="ab" * 32)
            doc = json.loads(path.read_text())
            self.assertEqual((doc["gen_seed"], doc["n_bases"], doc["strata"]), (GEN_SEED, 100, {"broad": 80, "thin": 20}))
            self.assertEqual([b.canonical for b in load_bases(path)], [b.canonical for b in self.bases])
            self.assertEqual(load_bases(path)[0].to_criteria().window_end, self.bases[0].criteria["window_end"])


if __name__ == "__main__":
    unittest.main()
