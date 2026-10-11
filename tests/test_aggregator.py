import unittest

import pandas as pd

from plotline.agents import aggregator
from plotline.contract import Criteria, window_months
from plotline.state import DataInfo, Failure, L1Request
from plotline.trace import TraceLog
from helpers import small_df

INFO = DataInfo(first_month="2014-01", latest_month="2015-02")


def agg(criteria: Criteria, rows: pd.DataFrame | None = None, df: pd.DataFrame | None = None):
    df = small_df() if df is None else df
    return aggregator.aggregate(criteria, df if rows is None else rows, df, INFO, TraceLog())


class Validation(unittest.TestCase):
    def test_missing_column_is_e_schema(self):
        out = agg(Criteria(window_end="2015-02"), df=small_df().drop(columns=["bhk"]))
        self.assertEqual((type(out), out.error.code), (Failure, "E_SCHEMA"))

    def test_l1_issues_found_in_one_pass(self):
        out = agg(Criteria(window_end="2016-01", price_band=[9, 1], bhk=[7], localities=["Adyr"]))
        self.assertIsInstance(out, L1Request)
        self.assertEqual(set(out.issues), {"band_inverted", "locality_unknown", "bhk_out_of_range", "window_out_of_range"})
        self.assertEqual(len(out.fields), 4)

    def test_valid_window_range_comes_from_the_data(self):
        self.assertIsInstance(agg(Criteria(window_end="2014-11")), L1Request)
        self.assertIsInstance(agg(Criteria(window_end="2014-12")), list)

    def test_inverted_sqft_range_is_not_repairable(self):
        out = agg(Criteria(window_end="2015-02", sqft_range=[2000, 1000]))
        self.assertEqual(out.error.code, "E_INVALID_CRITERIA")
        self.assertIn("sqft_range", out.error.message)


class Grid(unittest.TestCase):
    def test_dense_keys_depend_only_on_criteria(self):  # I-DENSE
        c = Criteria(window_end="2015-02", localities=["T Nagar", "Adyar"])
        empty = agg(c, rows=small_df().iloc[0:0])
        full = agg(c)
        keys = [(r.month, r.region_key) for r in empty]
        self.assertEqual(keys, [(r.month, r.region_key) for r in full])
        self.assertEqual(keys[:3], [("2014-03", "ALL"), ("2014-03", "Adyar"), ("2014-03", "T Nagar")])
        self.assertEqual(len(keys), 12 * 3)
        self.assertTrue(all(r.median_price is None and r.low_sample for r in empty))

    def test_counts_medians_and_pooled_all(self):
        df = pd.DataFrame({
            "listing_id": list("abcde"), "locality": ["Adyar", "Adyar", "T Nagar", "T Nagar", "T Nagar"],
            "sqft": [100, 200, 100, 100, 0], "sale_date": ["2015-02-01"] * 5, "bhk": [1] * 5,
            "sale_cond": ["Family"] * 5, "price": [1000, 3000, 5000, float("nan"), 7000],
        })
        recs = {(r.month, r.region_key): r for r in agg(Criteria(window_end="2015-02"), df=df)}
        a = recs[("2015-02", "ALL")]
        self.assertEqual((a.listing_count, a.n_in_bucket, a.median_price, a.median_price_per_sqft), (5, 3, 3000.0, 15.0))
        self.assertEqual((recs[("2015-02", "Adyar")].median_price, recs[("2015-02", "Adyar")].median_price_per_sqft), (2000.0, 12.5))
        t = recs[("2015-02", "T Nagar")]
        self.assertEqual((t.listing_count, t.n_in_bucket, t.median_price), (3, 1, 5000.0))
        self.assertIsNone(recs[("2015-01", "ALL")].median_price)
        self.assertTrue(all(r.pct_change_price_per_sqft is None for r in recs.values()))  # E fills it

    def test_row_order_does_not_matter(self):  # I-ORDER: bit-exact
        c = Criteria(window_end="2015-02")
        a = agg(c)
        b = agg(c, df=small_df().iloc[::-1].reset_index(drop=True))
        self.assertEqual(a, b)

    def test_window_months(self):
        recs = agg(Criteria(window_end="2014-12"))
        self.assertEqual(sorted({r.month for r in recs}), window_months("2014-12"))


if __name__ == "__main__":
    unittest.main()
