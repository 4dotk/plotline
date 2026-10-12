import unittest

import pandas as pd

from plotline.agents import anomaly
from plotline.contract import ANOMALY_PCT, Criteria, TrendRecord, window_months
from plotline.trace import TraceLog

END = "2014-12"
MONTHS = window_months(END)
CRIT = Criteria(window_end=END)


def series(ppsf: list[float | None], counts: list[int]) -> list[TrendRecord]:
    return [
        TrendRecord(month=m, region_key="ALL", listing_count=n, n_in_bucket=n,
                    median_price=None if p is None else p * 100, median_price_per_sqft=p,
                    low_sample=n < 5, pct_change_price_per_sqft=None)
        for m, p, n in zip(MONTHS, ppsf, counts)
    ]


def analyse(records, rows=None):
    rows = pd.DataFrame(columns=["sale_date", "price", "sqft"]) if rows is None else rows
    return anomaly.analyse(records, rows, CRIT, TraceLog())


class Flags(unittest.TestCase):
    def test_strictly_greater_than_the_threshold(self):
        above = 10 * (1 + ANOMALY_PCT + 1e-6)
        a = analyse(series([10, above] + [above] * 10, [10] * 12))
        self.assertEqual([(f.month, f.kind) for f in a.flags], [(MONTHS[1], "price_jump")])
        b = analyse(series([10, 10 * 1.12] + [10 * 1.12] * 10, [10] * 12))
        exact = b.records[1].pct_change_price_per_sqft
        self.assertEqual(bool(b.flags), abs(exact) > ANOMALY_PCT)  # decided on the computed value, > not >=

    def test_first_month_never_flagged_and_null_predecessors(self):
        a = analyse(series([10, 20, None, 10] + [10] * 8, [10, 10, 0, 10] + [10] * 8))
        pct = [r.pct_change_price_per_sqft for r in a.records]
        self.assertEqual((pct[0], pct[2], pct[3]), (None, None, None))  # first; empty; after empty
        self.assertEqual([(f.month, f.kind) for f in a.flags],
                         [(MONTHS[1], "price_jump"), (MONTHS[2], "count_drop")])

    def test_count_drop_needs_a_covered_predecessor(self):
        a = analyse(series([10] * 12, [4, 1] + [10] * 10))
        self.assertEqual([f.kind for f in a.flags], [])  # month 0 has 4 < MIN_BUCKET_N rows

    def test_scaling_prices_changes_no_flag(self):  # I-UNIT
        base = [10, 13, 9, 9.5, 12, 12, 7, 7, 7.5, 8, 9, 9]
        counts = [10, 10, 4, 10, 10, 5, 10, 10, 10, 10, 10, 10]
        ref = analyse(series(base, counts)).flags
        for k in (1e-5, 2, 4, 10):
            got = analyse(series([p * k for p in base], counts)).flags
            self.assertEqual([(f.month, f.kind) for f in got], [(f.month, f.kind) for f in ref])

    def test_locality_records_untouched(self):
        recs = series([10] * 12, [10] * 12)
        recs.append(TrendRecord(month=MONTHS[1], region_key="Adyar", listing_count=5, n_in_bucket=5,
                                median_price=1.0, median_price_per_sqft=1.0, low_sample=False,
                                pct_change_price_per_sqft=None))
        a = analyse(recs)
        self.assertIsNone(a.records[-1].pct_change_price_per_sqft)
        self.assertEqual(a.records[1].pct_change_price_per_sqft, 0.0)


class SummaryStats(unittest.TestCase):
    def rows(self, by_month: dict[str, list[int]]) -> pd.DataFrame:
        return pd.DataFrame([dict(sale_date=f"{m}-10", price=p, sqft=100) for m, ps in by_month.items() for p in ps])

    def test_pooled_first_and_last_three_months(self):
        rows = self.rows({MONTHS[0]: [100, 200, 300], MONTHS[2]: [1000, 1100], MONTHS[-1]: [150, 250, 350, 450, 550]})
        s = analyse(series([None] * 12, [0] * 12), rows).summary
        self.assertEqual((s.n_rows, s.price.start, s.price.end, s.price.direction), (10, 300.0, 350.0, "up"))
        self.assertEqual((s.price_per_sqft.start, s.price_per_sqft.end), (3.0, 3.5))

    def test_flat_band_and_too_few_rows(self):
        rows = self.rows({MONTHS[0]: [200] * 5, MONTHS[-1]: [201] * 5})
        self.assertEqual(analyse(series([None] * 12, [0] * 12), rows).summary.price.direction, "flat")  # +0.5 %
        rows = self.rows({MONTHS[0]: [100] * 4, MONTHS[-1]: [101] * 5})
        s = analyse(series([None] * 12, [0] * 12), rows).summary
        self.assertEqual((s.n_rows, s.price, s.price_per_sqft), (9, None, None))


if __name__ == "__main__":
    unittest.main()
