import unittest
from pathlib import Path

import pandas as pd

from plotline.agents import planner, scanner
from plotline.contract import Criteria, RunOptions
from plotline.state import DataInfo, PlanResult
from plotline.trace import TraceLog

SNAPSHOT = Path(__file__).resolve().parents[3] / "data" / "chennai_snapshot.csv"
INFO = DataInfo(first_month="2014-01", latest_month="2015-02")


def frame() -> pd.DataFrame:
    """Rows chosen to sit on every filter boundary (window 2015-02 = 2014-03 .. 2015-02)."""
    return pd.DataFrame(
        {
            "listing_id": ["P1", "P2", "P3", "P4", "P5", "P6", "P6"],
            "locality": ["Adyar", "Adyar", "T Nagar", "Chrompet", "Velachery", "KK Nagar", "KK Nagar"],
            "sqft": [1000, 1500, 900, 2000, 1200, 800, 800],
            "sale_date": ["2014-02-28", "2014-03-01", "2015-02-10", "2014-08-15", "2014-12-31", "2014-06-01", "2014-06-01"],
            "bhk": [1, 2, 2, 3, 4, 1, 1],
            "sale_cond": ["Normal Sale", "Family", "Partial", "AbNormal", "AdjLand", "Family", "Family"],
            "price": [5000000, 7000000, 6500000, 9000000, 7000000, 4000000, 4000000],
        }
    )


def plan(criteria: Criteria, topology: str | None = None) -> PlanResult:
    return planner.plan(criteria, INFO, RunOptions(force_topology=topology), 0, "off", TraceLog())


def ids(rows: pd.DataFrame) -> list[str]:
    return sorted(rows["listing_id"])


class Filters(unittest.TestCase):
    def scan(self, criteria: Criteria, topology: str | None = None) -> pd.DataFrame:
        return scanner.scan(plan(criteria, topology), frame(), TraceLog())

    def test_window_is_inclusive_twelve_months(self):
        self.assertEqual(ids(self.scan(Criteria())), ["P2", "P3", "P4", "P5", "P6", "P6"])  # P1 is 2014-02

    def test_each_filter_in_isolation_with_inclusive_bounds(self):
        self.assertEqual(ids(self.scan(Criteria(localities=["Adyar"]))), ["P2"])
        self.assertEqual(ids(self.scan(Criteria(bhk=[2]))), ["P2", "P3"])
        self.assertEqual(ids(self.scan(Criteria(price_band=[6500000, 7000000]))), ["P2", "P3", "P5"])
        self.assertEqual(ids(self.scan(Criteria(sqft_range=[900, 1200]))), ["P3", "P5"])
        self.assertEqual(ids(self.scan(Criteria(sale_cond=["Family"]))), ["P2", "P6", "P6"])

    def test_no_unit_conversion(self):  # D6: price_unit is a label only
        self.assertEqual(ids(self.scan(Criteria(price_band=[65, 70], price_unit="lakh"))), [])

    def test_lists_are_sets(self):
        a = self.scan(Criteria(bhk=[1, 2, 2], localities=["Adyar", "KK Nagar", "Adyar"]))
        b = self.scan(Criteria(bhk=[2, 1], localities=["KK Nagar", "Adyar"]))
        self.assertEqual(ids(a), ids(b))

    def test_duplicates_are_kept(self):  # D3, I-NODEDUPE
        self.assertEqual(ids(self.scan(Criteria(localities=["KK Nagar"]))), ["P6", "P6"])

    def test_empty_result_is_not_an_error(self):
        rows = self.scan(Criteria(localities=["Anna Nagar"]))
        self.assertEqual((len(rows), list(rows.columns)), (0, list(frame().columns)))

    def test_invalid_criteria_are_applied_literally(self):
        self.assertEqual(len(self.scan(Criteria(price_band=[9, 1]))), 0)
        self.assertEqual(len(self.scan(Criteria(localities=["Nowhere"]))), 0)

    def test_input_frame_unchanged_and_result_is_a_copy(self):  # I-PURE
        df = frame()
        df0 = df.copy(deep=True)
        rows = scanner.scan(plan(Criteria()), df, TraceLog())
        rows.loc[rows.index[0], "price"] = -1
        pd.testing.assert_frame_equal(df, df0)


class Topology(unittest.TestCase):
    CASES = [
        Criteria(),
        Criteria(localities=["Adyar", "T Nagar"]),
        Criteria(localities=["Adyar", "T Nagar", "KK Nagar"], bhk=[1, 2]),
        Criteria(price_band=[5000000, 9000000], sale_cond=["Family", "Partial"]),
    ]

    def test_parallel_and_consolidated_return_the_same_rows(self):  # I-TOPO
        for c in self.CASES:
            with self.subTest(criteria=c):
                par = scanner.scan(plan(c, "parallel"), frame(), TraceLog())
                con = scanner.scan(plan(c, "consolidated"), frame(), TraceLog())
                cols = list(frame().columns)
                pd.testing.assert_frame_equal(
                    par.sort_values(cols).reset_index(drop=True), con.sort_values(cols).reset_index(drop=True)
                )

    def test_stray_locality_is_outside_null_localities_in_both_topologies(self):
        df = pd.concat([frame(), frame().iloc[[2]].assign(listing_id="X1", locality="Elsewhere")])
        for topology in ("parallel", "consolidated"):
            self.assertNotIn("X1", ids(scanner.scan(plan(Criteria(), topology), df, TraceLog())))

    def test_one_trace_step_with_scanner_counts(self):
        trace = TraceLog()
        scanner.scan(plan(Criteria()), frame(), trace)
        (ev,) = trace.events
        self.assertEqual((ev.agent, ev.kind), ("scanner", "step"))
        self.assertEqual(ev.msg, "scan: 7 scanner(s), parallel: 6 rows")
        self.assertEqual(ev.data["per_scanner"]["KK Nagar"], 2)


@unittest.skipUnless(SNAPSHOT.is_file(), "frozen snapshot not present")
class Golden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(SNAPSHOT)
        months = cls.df["sale_date"].str[:7]
        cls.info = DataInfo(first_month=str(months.min()), latest_month=str(months.max()))

    def rows(self, criteria: Criteria, topology: str | None = None) -> int:
        p = planner.plan(criteria, self.info, RunOptions(force_topology=topology), 0, "off", TraceLog())
        return len(scanner.scan(p, self.df, TraceLog()))

    def test_a1_row_counts(self):  # golden.md A1
        self.assertEqual(self.rows(Criteria()), 338)
        self.assertEqual(self.rows(Criteria(window_end="2011-12")), 1300)
        self.assertEqual(self.rows(Criteria(window_end="2011-12"), "consolidated"), 1300)

    def test_a3_widening_row_counts(self):  # golden.md A3: 38 -> 49 -> 71
        bands = [[7000000, 9000000], [6600000, 9400000], [6000000, 10000000]]
        got = [self.rows(Criteria(localities=["Adyar"], bhk=[1], price_band=b, window_end="2010-12")) for b in bands]
        self.assertEqual(got, [38, 49, 71])


if __name__ == "__main__":
    unittest.main()
