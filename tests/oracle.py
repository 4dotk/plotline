"""Independent test oracle: CONTRACT.md 6.2-6.3 in plain pandas (contracts/Testing.md section 2).

It MUST NOT import application logic. The only allowed import from the
application is ``plotline.contract`` (constants and the month helpers that
define the window, Testing.md clarification 1), so thresholds cannot drift.

The oracle works from a report's ``effective_criteria``, so L1 repairs and L2
widening are covered without re-implementing the loops (Testing.md 2.4). It
returns plain dicts shaped like the report fields it covers:

    records          list of TrendRecord-shaped dicts (dense grid)
    coverage_score   float
    anomaly_flags    list of {month, region_key, kind, value, threshold}
    summary          {n_rows, price, price_per_sqft}
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from plotline.contract import (
    ALL_REGION,
    ANOMALY_PCT,
    CANONICAL_LOCALITIES,
    COUNT_DROP,
    FLAT_BAND_PCT,
    MIN_BUCKET_N,
    WINDOW_MONTHS,
    window_months,
)

SUMMARY_MONTHS = 3  # first-3 vs last-3 months (6.1); a contract word, not a section 3 constant


def _median(values: pd.Series) -> float | None:
    return float(np.median(np.sort(values.to_numpy(dtype="float64")))) if len(values) else None


def matching_rows(df: pd.DataFrame, criteria: dict) -> pd.DataFrame:
    """Rows of ``df`` matching ``criteria`` (a Criteria dict) inside the window, written
    from 5.2 / 4.4 directly. ``localities`` null means all 7 canonical names."""
    c = criteria
    months = df["sale_date"].astype(str).str.slice(0, 7)
    keep = months.isin(window_months(c["window_end"]))
    keep &= df["locality"].isin(c["localities"] if c["localities"] is not None else CANONICAL_LOCALITIES)
    if c["bhk"] is not None:
        keep &= df["bhk"].isin(c["bhk"])
    if c["price_band"] is not None:
        lo, hi = c["price_band"]
        keep &= (df["price"] >= lo) & (df["price"] <= hi)
    if c["sqft_range"] is not None:
        lo, hi = c["sqft_range"]
        keep &= (df["sqft"] >= lo) & (df["sqft"] <= hi)
    if c["sale_cond"] is not None:
        keep &= df["sale_cond"].isin(c["sale_cond"])
    out = df.loc[keep, ["locality", "sqft", "price"]].copy()
    out["month"] = months[keep]
    return out


def _valid(rows: pd.DataFrame) -> pd.DataFrame:
    """Rows usable for medians: finite price > 0 and sqft > 0 (data.md 5.10)."""
    price = rows["price"].astype("float64")
    sqft = rows["sqft"].astype("float64")
    return rows[np.isfinite(price) & (price > 0) & (sqft > 0)]


def _bucket(rows: pd.DataFrame, month: str, region: str) -> dict:
    valid = _valid(rows)
    n = len(valid)
    ppsf = valid["price"].astype("float64") / valid["sqft"].astype("float64")
    return {
        "month": month, "region_key": region,
        "listing_count": len(rows), "n_in_bucket": n,
        "median_price": _median(valid["price"]), "median_price_per_sqft": _median(ppsf),
        "low_sample": n < MIN_BUCKET_N, "pct_change_price_per_sqft": None,
    }


def _stat_change(start: float, end: float) -> dict:
    change = (end / start - 1) * 100
    direction = "up" if change > FLAT_BAND_PCT else "down" if change < -FLAT_BAND_PCT else "flat"
    return {"start": start, "end": end, "change_pct": change, "direction": direction}


def oracle(df: pd.DataFrame, criteria: dict) -> dict:
    """Expected report fields for ``criteria`` (the report's ``effective_criteria``)."""
    rows = matching_rows(df, criteria)
    months = window_months(criteria["window_end"])
    locs = sorted(set(criteria["localities"])) if criteria["localities"] is not None else sorted(CANONICAL_LOCALITIES)

    records, all_series = [], []
    for m in months:
        in_month = rows[rows["month"] == m]
        rec = _bucket(in_month, m, ALL_REGION)
        all_series.append(rec)
        records.append(rec)
        for loc in locs:
            records.append(_bucket(in_month[in_month["locality"] == loc], m, loc))

    flags = []
    for t in range(1, len(all_series)):
        prev, cur = all_series[t - 1], all_series[t]
        if prev["n_in_bucket"] >= MIN_BUCKET_N and cur["n_in_bucket"] >= MIN_BUCKET_N:
            pct = cur["median_price_per_sqft"] / prev["median_price_per_sqft"] - 1
            cur["pct_change_price_per_sqft"] = pct
            if abs(pct) > ANOMALY_PCT:
                flags.append({"month": cur["month"], "region_key": ALL_REGION, "kind": "price_jump",
                              "value": pct, "threshold": ANOMALY_PCT})
        if prev["n_in_bucket"] >= MIN_BUCKET_N and cur["listing_count"] <= COUNT_DROP * prev["listing_count"]:
            flags.append({"month": cur["month"], "region_key": ALL_REGION, "kind": "count_drop",
                          "value": cur["listing_count"] / prev["listing_count"], "threshold": COUNT_DROP})

    first = _valid(rows[rows["month"].isin(months[:SUMMARY_MONTHS])])
    last = _valid(rows[rows["month"].isin(months[-SUMMARY_MONTHS:])])
    summary = {"n_rows": len(rows), "price": None, "price_per_sqft": None}
    if len(first) >= MIN_BUCKET_N and len(last) >= MIN_BUCKET_N:
        summary["price"] = _stat_change(_median(first["price"]), _median(last["price"]))
        summary["price_per_sqft"] = _stat_change(
            _median(first["price"].astype("float64") / first["sqft"]),
            _median(last["price"].astype("float64") / last["sqft"]),
        )

    covered = sum(1 for r in all_series if r["n_in_bucket"] >= MIN_BUCKET_N)
    return {
        "records": records,
        "coverage_score": covered / WINDOW_MONTHS,
        "anomaly_flags": flags,
        "summary": summary,
    }
