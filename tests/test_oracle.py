"""Oracle self-tests (Testing.md 2.3 and 11, T23), then the application against the oracle."""

import ast
import math
import unittest
from pathlib import Path

import pandas as pd

from plotline.contract import REL_TOL, Criteria, window_months
from plotline.orchestrator import Engine
from tests.oracle import oracle
from helpers import A1, SNAPSHOT_SHA

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data" / "chennai_snapshot.csv"
NO_FILTERS = dict(localities=None, bhk=None, price_band=None, sqft_range=None, sale_cond=None, price_unit="inr")


def close(a, b) -> bool:
    return math.isclose(a, b, rel_tol=REL_TOL)


def all_series(result: dict) -> list[dict]:
    return sorted((r for r in result["records"] if r["region_key"] == "ALL"), key=lambda r: r["month"])


class Independence(unittest.TestCase):
    def test_oracle_imports_only_the_contract_module(self):  # Testing.md 2.1
        tree = ast.parse((ROOT / "tests" / "oracle.py").read_text())
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertEqual({m for m in modules if m.startswith("plotline")}, {"plotline.contract"})


@unittest.skipUnless(SNAPSHOT.is_file(), "frozen snapshot not present")
class Golden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(SNAPSHOT)

    def test_a1(self):
        o = oracle(self.df, {**NO_FILTERS, "window_end": "2015-02"})
        series = all_series(o)
        self.assertEqual([r["month"] for r in series], [m for m, *_ in A1])
        for r, (month, n, mp, mpps, pct) in zip(series, A1):
            with self.subTest(month=month):
                self.assertEqual((r["listing_count"], r["n_in_bucket"]), (n, n))
                self.assertTrue(close(r["median_price"], mp))
                self.assertTrue(close(r["median_price_per_sqft"], mpps))
                if pct is None:
                    self.assertIsNone(r["pct_change_price_per_sqft"])
                else:
                    self.assertAlmostEqual(r["pct_change_price_per_sqft"], pct, places=10)
        self.assertEqual([(f["month"], f["kind"]) for f in o["anomaly_flags"]],
                         [("2014-12", "price_jump"), ("2015-01", "price_jump")])
        s = o["summary"]
        self.assertEqual((s["n_rows"], s["price"]["start"], s["price"]["end"], s["price_per_sqft"]["end"]),
                         (338, 12303430.0, 11618510.0, 8945.0))
        self.assertAlmostEqual(s["price"]["change_pct"], -5.566902888, places=8)
        self.assertAlmostEqual(s["price_per_sqft"]["change_pct"], 5.335864105, places=8)
        self.assertEqual((s["price"]["direction"], s["price_per_sqft"]["direction"]), ("down", "up"))
        self.assertEqual(o["coverage_score"], 1.0)
        per_loc = {}
        for r in o["records"]:
            if r["region_key"] != "ALL":
                per_loc[r["region_key"]] = per_loc.get(r["region_key"], 0) + r["listing_count"]
        self.assertEqual({k: v for k, v in per_loc.items() if v},
                         {"Anna Nagar": 96, "Chrompet": 186, "T Nagar": 56})
        self.assertEqual(len(o["records"]), 12 * 8)  # dense grid: the 4 empty localities too

    def test_a2(self):
        o = oracle(self.df, {**NO_FILTERS, "window_end": "2011-12"})
        s = o["summary"]
        self.assertEqual((s["n_rows"], o["coverage_score"], o["anomaly_flags"]), (1300, 1.0, []))
        self.assertEqual((s["price"]["start"], s["price"]["end"]), (10481780.0, 9493200.0))
        self.assertAlmostEqual(s["price"]["change_pct"], -9.431413367, places=8)
        self.assertAlmostEqual(s["price_per_sqft"]["start"], 7855.461839, places=5)
        self.assertAlmostEqual(s["price_per_sqft"]["end"], 7478.921224, places=5)
        self.assertAlmostEqual(s["price_per_sqft"]["change_pct"], -4.793360633, places=8)


def rows(month_rows: dict[str, list[tuple]]) -> pd.DataFrame:
    """{month: [(locality, sqft, price), ...]} -> a snapshot-shaped frame."""
    out = []
    for month, items in month_rows.items():
        for i, (loc, sqft, price) in enumerate(items):
            out.append(dict(listing_id=f"{month}-{i}", locality=loc, sqft=sqft, sale_date=f"{month}-15",
                            bhk=2, sale_cond="Normal Sale", price=price))
    return pd.DataFrame(out)


class HandCalculations(unittest.TestCase):
    """Three cases worked out by hand (Testing.md 2.3.1)."""

    END = "2014-12"
    MONTHS = window_months(END)

    def run_oracle(self, df, **criteria):
        return oracle(df, {**NO_FILTERS, "window_end": self.END, **criteria})

    def test_1_medians_odd_even_and_invalid_rows(self):
        m = self.MONTHS[0]
        df = rows({m: [("Adyar", 100, 1000), ("Adyar", 200, 3000), ("Chrompet", 100, 5000),
                       ("Chrompet", 0, 9000)]})  # sqft 0: counted, not in the medians
        o = self.run_oracle(df, localities=["Adyar", "Chrompet"])
        rec = {(r["month"], r["region_key"]): r for r in o["records"]}
        all_ = rec[(m, "ALL")]
        # valid prices 1000, 3000, 5000 -> 3000; ppsf 10, 15, 50 -> 15
        self.assertEqual((all_["listing_count"], all_["n_in_bucket"]), (4, 3))
        self.assertEqual((all_["median_price"], all_["median_price_per_sqft"], all_["low_sample"]), (3000.0, 15.0, True))
        adyar = rec[(m, "Adyar")]  # even count: mean of the two middle values
        self.assertEqual((adyar["median_price"], adyar["median_price_per_sqft"]), (2000.0, 12.5))
        empty = rec[(self.MONTHS[1], "ALL")]
        self.assertEqual((empty["listing_count"], empty["median_price"]), (0, None))
        self.assertEqual(len(o["records"]), 12 * 3)

    def test_2_pct_change_and_flags(self):
        m0, m1, m2, m3 = self.MONTHS[:4]
        five = lambda price: [("Adyar", 100, price)] * 5
        df = rows({m0: five(1000) * 2, m1: five(1130) * 2, m2: five(1130), m3: [("Adyar", 100, 900)] * 4})
        o = self.run_oracle(df)
        s = all_series(o)
        # ppsf 10 -> 11.3: +13 % > 12 % -> price_jump; m2: 5 rows <= 0.5 x 10 -> count_drop;
        # m3: 4 rows > 0.5 x 5, so no flag, and its pct_change is null (4 < MIN_BUCKET_N)
        self.assertIsNone(s[0]["pct_change_price_per_sqft"])
        self.assertAlmostEqual(s[1]["pct_change_price_per_sqft"], 0.13, places=12)
        self.assertEqual(s[2]["pct_change_price_per_sqft"], 0.0)
        self.assertIsNone(s[3]["pct_change_price_per_sqft"])  # m3 has only 4 rows
        got = [(f["month"], f["kind"]) for f in o["anomaly_flags"]]
        self.assertEqual(got, [(m1, "price_jump"), (m2, "count_drop")])
        self.assertEqual(o["anomaly_flags"][1]["value"], 0.5)
        self.assertEqual(o["coverage_score"], 3 / 12)

    def test_3_summary_is_pooled_not_averaged(self):
        first = {self.MONTHS[0]: [("Adyar", 100, p) for p in (100, 200, 300)],
                 self.MONTHS[1]: [("Adyar", 100, p) for p in (1000, 1100)]}
        last = {self.MONTHS[-1]: [("Adyar", 100, p) for p in (150, 250, 350, 450, 550)]}
        o = self.run_oracle(rows({**first, **last}))
        s = o["summary"]
        # pooled first-3: 100 200 300 1000 1100 -> 300 (the mean of monthly medians would be 625)
        self.assertEqual((s["n_rows"], s["price"]["start"], s["price"]["end"]), (10, 300.0, 350.0))
        self.assertAlmostEqual(s["price"]["change_pct"], 50 / 3, places=12)
        self.assertEqual(s["price"]["direction"], "up")
        # fewer than MIN_BUCKET_N pooled rows on one side -> both stats null
        o = self.run_oracle(rows(first))
        self.assertEqual((o["summary"]["price"], o["summary"]["price_per_sqft"]), (None, None))


def compare(case: unittest.TestCase, report, df: pd.DataFrame) -> None:
    """Application vs oracle, Testing.md section 3 comparators."""
    d = report.model_dump(mode="json")
    o = oracle(df, d["effective_criteria"])
    key = lambda r: (r["month"], r["region_key"])
    app, exp = {key(r): r for r in d["records"]}, {key(r): r for r in o["records"]}
    case.assertEqual(set(app), set(exp))  # I-DENSE
    for k, e in exp.items():
        a = app[k]
        for f in ("listing_count", "n_in_bucket", "low_sample"):
            case.assertEqual(a[f], e[f], (k, f))
        for f in ("median_price", "median_price_per_sqft", "pct_change_price_per_sqft"):
            case.assertEqual(a[f] is None, e[f] is None, (k, f))
            if e[f] is not None:
                case.assertTrue(close(a[f], e[f]), (k, f, a[f], e[f]))
    case.assertEqual(d["coverage_score"], o["coverage_score"])
    flags = {(f["month"], f["region_key"], f["kind"]): f["value"] for f in d["anomaly_flags"]}
    case.assertEqual(set(flags), {(f["month"], f["region_key"], f["kind"]) for f in o["anomaly_flags"]})
    for f in o["anomaly_flags"]:
        case.assertTrue(close(flags[(f["month"], f["region_key"], f["kind"])], f["value"]))
    case.assertEqual(d["summary"]["n_rows"], o["summary"]["n_rows"])
    for stat in ("price", "price_per_sqft"):
        a, e = d["summary"][stat], o["summary"][stat]
        case.assertEqual(a is None, e is None, stat)
        if e is not None:
            case.assertEqual(a["direction"], e["direction"])
            case.assertTrue(close(a["start"], e["start"]) and close(a["end"], e["end"]))
            case.assertLessEqual(abs(a["change_pct"] - e["change_pct"]), 1e-7)


@unittest.skipUnless(SNAPSHOT.is_file(), "frozen snapshot not present")
class ApplicationAgainstOracle(unittest.TestCase):
    CASES = [
        Criteria(),
        Criteria(window_end="2011-12"),
        Criteria(localities=["Adyar"], bhk=[1], price_band=[7000000, 9000000], window_end="2010-12"),
        Criteria(localities=["Velachery", "KK Nagar"], bhk=[2], window_end="2008-06"),
        Criteria(localities=["T Nagar", "Chrompet", "Anna Nagar"], price_band=[5000000, 15000000], window_end="2013-03"),
        Criteria(sqft_range=[900, 1400], sale_cond=["Family", "Partial"], window_end="2006-09"),
    ]

    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(SNAPSHOT)
        cls.engine = Engine(SNAPSHOT_SHA, logic_version="abc1234")

    def test_every_case_matches_the_oracle(self):
        for c in self.CASES:
            with self.subTest(criteria=c):
                r = self.engine.run(c, self.df)
                self.assertEqual(r.status, "ok")
                compare(self, r, self.df)

    def test_a3_l2_worked_example(self):  # golden.md A3
        r = self.engine.run(self.CASES[2], self.df)
        loops = [e for e in r.trace if e.loop == "L2"]
        self.assertEqual([e.data["coverage_months"] for e in loops], [3, 6])
        self.assertEqual([e.data["effective_price_band"] for e in loops], [[6600000.0, 9400000.0], [6000000.0, 10000000.0]])
        self.assertEqual((r.metadata.loop_counters.L2_attempts, r.coverage_score), (2, 9 / 12))
        self.assertEqual(r.summary.n_rows, 71)

    def test_topology_does_not_change_numbers(self):  # I-TOPO
        from plotline.contract import RunOptions, report_to_json
        import json
        for c in self.CASES[:3]:
            a = json.loads(report_to_json(self.engine.run(c, self.df, options=RunOptions(force_topology="parallel"))))
            b = json.loads(report_to_json(self.engine.run(c, self.df, options=RunOptions(force_topology="consolidated"))))
            for d in (a, b):
                d.pop("trace"), d.pop("metadata")
            self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
