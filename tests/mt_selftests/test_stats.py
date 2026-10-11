"""Statistics self-tests: the known cases of contracts/Testing.md 8 (T24)."""

import tempfile
import unittest
from pathlib import Path

from tests.mt.stats import MRResult, clopper_pearson, headline_table, interval, wilson, write_headline_table


class Intervals(unittest.TestCase):
    def test_wilson_non_boundary(self):
        # 5 of 50 by hand: z = 1.959964, centre 0.128539, half-width 0.085063
        ci = interval(5, 50)
        self.assertEqual(ci.method, "Wilson")
        self.assertAlmostEqual(ci.lo, 0.043476, places=5)
        self.assertAlmostEqual(ci.hi, 0.213602, places=5)
        self.assertLess(ci.lo, 5 / 50)
        self.assertGreater(ci.hi, 5 / 50)

    def test_zero_violations_upper_bounds(self):
        for n, upper in ((30, 0.116), (100, 0.036)):
            with self.subTest(n=n):
                ci = interval(0, n)
                self.assertEqual((ci.method, ci.lo), ("Clopper-Pearson", 0.0))
                self.assertAlmostEqual(ci.hi, 1 - 0.025 ** (1 / n), places=12)
                self.assertAlmostEqual(ci.hi, upper, places=3)

    def test_all_violations_is_clopper_pearson(self):
        ci = interval(30, 30)
        self.assertEqual((ci.method, ci.hi), ("Clopper-Pearson", 1.0))
        self.assertAlmostEqual(ci.lo, 0.025 ** (1 / 30), places=12)

    def test_clopper_pearson_contains_wilson_centre(self):
        cp, w = clopper_pearson(5, 50), wilson(5, 50)
        self.assertLessEqual(cp.lo, w.lo)  # Clopper-Pearson is the more conservative one
        self.assertGreaterEqual(cp.hi, w.hi)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            interval(0, 0)
        with self.assertRaises(ValueError):
            interval(5, 4)


class Table(unittest.TestCase):
    RESULTS = [
        MRResult("1", "invariance", (0,), 100, 0),
        MRResult("3a", "invariance", (0,), 120, 2, skipped={"n_in_bucket in {3,4}": 15, "L2_attempts > 0": 5},
                 unconditioned=(6, 115)),
        MRResult("9", "invariance", (101, 202, 303), 30, 1, pairs=90, pair_violations=1),
        MRResult("4", "monotonic", (0,), 10, 0, skipped={"price_band set": 10}),
    ]

    def test_rows_and_columns(self):
        text = headline_table(self.RESULTS)
        rows = [line for line in text.splitlines() if line.startswith("| ") and not line.startswith("| MR")]
        self.assertEqual(len(rows), 4)
        cells = [c.strip() for c in rows[1].strip("|").split("|")]
        self.assertEqual(cells[:5], ["3a", "invariance", "0", "120", "100"])
        self.assertEqual(cells[5], "20 (L2_attempts > 0: 5; n_in_bucket in {3,4}: 15)")
        self.assertTrue(cells[6].startswith("2/100 = 2.0 % ["))
        self.assertTrue(cells[6].endswith("Wilson"))
        self.assertTrue(cells[8].startswith("6/115"))
        self.assertIn("0/100 = 0.0 % [0.0 %, 3.6 %] Clopper-Pearson", rows[0])
        self.assertIn("1/90", rows[2])  # Mode B per-pair rate
        self.assertIn("n/a (0 evaluated)", rows[3])  # all skipped: a skip is not a pass

    def test_written_to_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_headline_table(self.RESULTS, Path(d) / "results" / "headline_table.md")
            self.assertTrue(path.read_text().startswith("# Headline results"))


if __name__ == "__main__":
    unittest.main()
