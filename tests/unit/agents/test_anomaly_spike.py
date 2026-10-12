"""Anomaly check, end to end on the real snapshot: an inserted fake spike gets flagged.

Takes the frozen snapshot, injects a fake price spike (and, separately, a fake
listing drop-off) into one calm month of a copy, runs the whole engine and checks
that the matching flag appears with a reason, and that no flag appears without the
injection. Inputs and outputs are logged (see tests/conftest.py for where the logs go).
"""

from __future__ import annotations

import logging
import os
import unittest
from pathlib import Path

import pandas as pd

from plotline.contract import ANOMALY_PCT, COUNT_DROP, Criteria, window_months
from plotline.orchestrator import Engine

log = logging.getLogger("plotline.test.anomaly_spike")

DATA = Path(os.environ.get("CHENNAI_DATA_DIR", "data"))
SNAPSHOT = DATA / "chennai_snapshot.csv"
WINDOW_END = "2015-02"          # golden.md A1 window
CALM = "2014-06"                # no flag on the unmodified data
CRIT = Criteria(window_end=WINDOW_END)


def flags_of(report) -> dict[tuple[str, str], object]:
    return {(f.month, f.kind): f for f in report.anomaly_flags}


@unittest.skipUnless(SNAPSHOT.exists(), "snapshot not found (set CHENNAI_DATA_DIR)")
class InsertedSpike(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(SNAPSHOT)
        cls.engine = Engine.from_data_dir(DATA, llm_mode="off")
        cls.base = cls.engine.run(CRIT, cls.df)

    def run_on(self, df: pd.DataFrame):
        report = self.engine.run(CRIT, df)
        self.assertEqual(report.status, "ok")
        for f in report.anomaly_flags:
            log.info("FLAG %s %-10s value=%.4f threshold=%s reason=%s", f.month, f.kind, f.value, f.threshold, f.reason)
        return report

    def test_baseline_has_no_flag_in_the_calm_month(self):
        got = flags_of(self.base)
        log.info("baseline flags: %s", sorted(got))
        self.assertNotIn((CALM, "price_jump"), got)
        self.assertNotIn((CALM, "count_drop"), got)

    def test_fake_price_spike_is_flagged_with_a_reason(self):
        spiked = self.df.copy()
        in_month = spiked["sale_date"].str[:7] == CALM
        spiked.loc[in_month, "price"] = spiked.loc[in_month, "price"] * 1.5  # +50 % in one month
        log.info("IN   price x1.5 on %d rows in %s", int(in_month.sum()), CALM)
        report = self.run_on(spiked)

        flag = flags_of(report)[(CALM, "price_jump")]
        self.assertGreater(flag.value, ANOMALY_PCT)            # a rise
        self.assertAlmostEqual(flag.value, 0.5, delta=0.1)     # about the size of the injection
        self.assertEqual(flag.threshold, ANOMALY_PCT)
        self.assertEqual(flag.region_key, "ALL")
        self.assertTrue(flag.reason.strip())
        self.assertIn("rose", flag.reason)
        self.assertIn(window_months(WINDOW_END)[window_months(WINDOW_END).index(CALM) - 1], flag.reason)
        # the fall back to normal the month after is flagged too (month-on-month)
        nxt = window_months(WINDOW_END)[window_months(WINDOW_END).index(CALM) + 1]
        self.assertLess(flags_of(report)[(nxt, "price_jump")].value, -ANOMALY_PCT)
        # every flag has a diagnostic entry and a non-empty reason
        self.assertEqual(sorted(d.month for d in report.diagnostics), sorted(m for m, _ in flags_of(report)))
        self.assertTrue(all(f.reason.strip() for f in report.anomaly_flags))
        # the trace records the anomaly step
        self.assertTrue(any(e.agent == "anomaly" for e in report.trace))

    def test_fake_listing_drop_is_flagged_as_count_drop(self):
        month = "2014-09"
        dropped = self.df.copy()
        idx = dropped.index[dropped["sale_date"].str[:7] == month]
        keep = [i % 4 == 0 for i in range(len(idx))]          # keep every 4th row of the month
        dropped = dropped.drop(idx[[not k for k in keep]])
        n_before = len(idx)
        n_after = int((dropped["sale_date"].str[:7] == month).sum())
        log.info("IN   %s: %d rows -> %d rows", month, n_before, n_after)
        report = self.run_on(dropped)

        flag = flags_of(report)[(month, "count_drop")]
        self.assertLessEqual(flag.value, COUNT_DROP)
        self.assertEqual(flag.threshold, COUNT_DROP)
        self.assertIn("fell to", flag.reason)
        self.assertNotIn((month, "count_drop"), flags_of(self.base))

    def test_input_is_not_modified(self):  # I-PURE
        before = self.df.copy()
        self.engine.run(CRIT, self.df)
        pd.testing.assert_frame_equal(self.df, before)


if __name__ == "__main__":
    unittest.main()
