"""Agent H, the Inspector (1.2.0): requests are checked against what the data holds,
and nothing the system changed or could not find is invisible to the user.

Run on the real snapshot: the cases are questions people ask, and the answers
depend on what each locality actually holds (e.g. Adyar: 1-2 BHK, Oct 2006 - May 2012).
"""

import unittest
from pathlib import Path

import pandas as pd

from plotline.contract import Criteria
from plotline.llm_client import LlmClient, LlmConfig
from plotline.orchestrator import Engine
from plotline.state import DataInfo

ROOT = Path(__file__).resolve().parents[3]
DF = pd.read_csv(ROOT / "data" / "chennai_snapshot.csv")
ENGINE = Engine.from_data_dir(ROOT / "data", llm_client=LlmClient(LlmConfig(mode="off")), logic_version="abc1234")


def run(**criteria):
    return ENGINE.run(Criteria(**criteria), DF)


def told(report, kind=None):
    return [n.text for n in report.notices if kind is None or n.kind == kind]


class Profile(unittest.TestCase):
    def test_each_locality_has_its_own_range_and_bhk(self):
        info = DataInfo.from_df(DF)
        adyar = info.locality("Adyar")
        self.assertEqual((adyar.first_month, adyar.last_month, adyar.bhk), ("2006-10", "2012-05", (1, 2)))
        self.assertEqual(info.locality("Velachery").bhk, (2, 3))
        self.assertEqual(len(info.localities), 7)
        self.assertIsNone(info.locality("Hyderabad"))


class OutsideTheData(unittest.TestCase):
    def test_a_recent_year_is_repaired_and_said(self):
        """'2BHK in Adyar in 2023': L1 clamps the window, and Adyar has no sales after May 2012."""
        r = run(localities=["Adyar"], bhk=[2], window_end="2023-12")
        self.assertEqual((r.status, r.effective_criteria.window_end, r.metadata.loop_counters.L1_repairs),
                         ("ok", "2015-02", 1))
        repaired = told(r, "repaired")
        self.assertEqual(len(repaired), 1)
        self.assertIn("no data after Feb 2015 (you asked about Dec 2023)", repaired[0])
        self.assertIn("any 12 months ending between Dec 2004 and Feb 2015", repaired[0])
        empty = told(r, "no_sales")
        self.assertEqual(len(empty), 1)
        self.assertIn("No 2 BHK sales in the 12 months to Feb 2015", empty[0])
        self.assertIn("Adyar has 1–2 BHK sales from Oct 2006 to May 2012", empty[0])

    def test_a_city_that_is_not_in_the_data(self):
        """'Hyderabad trends': never answered for Chennai; the user is told what the data covers."""
        r = run(localities=["Hyderabad"])
        self.assertEqual((r.status, r.error.code), ("error", "E_INVALID_CRITERIA"))
        self.assertEqual([n.kind for n in r.notices], ["out_of_scope"])
        self.assertTrue(told(r)[0].startswith("'Hyderabad' is not in this data. This data covers 7 Chennai localities"))

    def test_more_bedrooms_than_the_data_has(self):
        r = run(localities=["KK Nagar"], bhk=[5])
        self.assertEqual((r.status, r.error.code), ("error", "E_INVALID_CRITERIA"))
        self.assertIn("This data has 1-4 BHK homes only; 5 BHK cannot be shown.", told(r, "out_of_scope")[0])

    def test_some_bedrooms_dropped_is_said(self):
        r = run(localities=["KK Nagar"], bhk=[4, 5], window_end="2011-12")
        self.assertEqual((r.status, r.effective_criteria.bhk), ("ok", [4]))
        self.assertIn("5 BHK was left out; showing 4 BHK", told(r, "repaired")[0])

    def test_budget_given_high_to_low(self):
        r = run(localities=["Chrompet"], price_band=[9_000_000, 7_000_000], window_end="2014-12")
        self.assertEqual(r.effective_criteria.price_band[0] <= r.effective_criteria.price_band[1], True)
        self.assertIn("given high to low; read as ₹70 lakh to ₹90 lakh", told(r, "repaired")[0])

    def test_inspector_acts_before_the_scan(self):
        r = run(localities=["Adyar"], window_end="2023-12")
        agents = [e.agent for e in r.trace]
        self.assertEqual(agents[:2], ["planner", "inspector"])  # checked before anything is scanned
        self.assertNotIn("scanner", agents[:agents.index("inspector") + 1])


class NoSales(unittest.TestCase):
    def test_a_bhk_the_locality_never_sold(self):
        """'3BHK in Adyar': valid, but Adyar has 1-2 BHK only. Say so, never a silent empty chart."""
        r = run(localities=["Adyar"], bhk=[3], window_end="2011-12")
        self.assertEqual(r.status, "ok")
        self.assertEqual(sum(x.listing_count for x in r.records), 0)
        self.assertIn("No 3 BHK sales in the 12 months to Dec 2011 for any requested locality", told(r, "no_sales")[0])
        self.assertIn("Adyar has 1–2 BHK sales", told(r, "no_sales")[0])

    def test_only_the_empty_locality_is_named(self):
        r = run(localities=["Adyar", "T Nagar"], window_end="2014-12")
        text = told(r, "no_sales")
        self.assertEqual(len(text), 1)
        self.assertIn("in Adyar.", text[0])
        self.assertNotIn("T Nagar has", text[0])

    def test_a_query_with_sales_gets_no_notice(self):
        r = run(localities=["Chrompet"], window_end="2014-12")
        self.assertEqual(r.notices, [])


class Widened(unittest.TestCase):
    def test_l2_widening_is_said(self):
        """MR10 base 321's source: L2 widens the band twice (44 -> 61 -> 73 rows)."""
        r = run(localities=["Anna Nagar"], window_end="2014-06", price_band=[12_401_250, 18_299_980])
        self.assertEqual(r.metadata.loop_counters.L2_attempts, 2)
        self.assertEqual(told(r, "widened"),
                         ["Too few sales matched your filters, so the price range was widened to ₹94.52 lakh – ₹2.125 crore."])


if __name__ == "__main__":
    unittest.main()
