"""Agent C: Result Aggregator (contracts/Aggregator.md).

Worker. First validates the criteria (problems go back to the Planner as an L1
request; it never repairs them itself), then builds the dense grid of monthly
buckets: counts and medians for ``ALL`` and every requested locality. It leaves
``pct_change_price_per_sqft`` null (E fills it) and computes nothing else.
"""

from __future__ import annotations

from typing import Union

import numpy as np
import pandas as pd

from plotline.contract import (
    ALL_REGION,
    CANONICAL_LOCALITIES,
    MIN_BUCKET_N,
    Criteria,
    ErrorInfo,
    TrendRecord,
    window_months,
)
from plotline.state import SNAPSHOT_COLUMNS, DataInfo, Failure, L1Request
from plotline.trace import TraceLog

ISSUE_FIELD = {
    "band_inverted": "price_band",
    "locality_unknown": "localities",
    "window_out_of_range": "window_end",
    "bhk_out_of_range": "bhk",
    "sale_cond_unknown": "sale_cond",
}


def validate_criteria(effective: Criteria, info: DataInfo) -> Union[L1Request, Failure, None]:
    """L1 issues found in one pass (one request), a non-repairable problem, or None."""
    if effective.sqft_range is not None and effective.sqft_range[0] > effective.sqft_range[1]:
        # not in the L1 repair table (Aggregator.md clarification)
        return Failure(ErrorInfo(code="E_INVALID_CRITERIA",
                                 message=f"invalid sqft_range: {effective.sqft_range} has lo > hi"))
    issues = list(effective.domain_violations())
    assert effective.window_end is not None
    if not info.first_valid_end <= effective.window_end <= info.latest_month:
        issues.append("window_out_of_range")
    if issues:
        return L1Request(issues=issues, fields=[ISSUE_FIELD[i] for i in issues])
    return None


def _median(values: np.ndarray) -> float | None:
    return float(np.median(np.sort(values))) if len(values) else None  # sorted: I-ORDER


def _record(month: str, region: str, count: int, price: np.ndarray, ppsf: np.ndarray) -> TrendRecord:
    n = len(price)
    return TrendRecord(
        month=month, region_key=region, listing_count=count, n_in_bucket=n,
        median_price=_median(price), median_price_per_sqft=_median(ppsf),
        low_sample=n < MIN_BUCKET_N, pct_change_price_per_sqft=None,
    )


def aggregate(
    effective: Criteria, rows: pd.DataFrame, df: pd.DataFrame, info: DataInfo, trace: TraceLog,
) -> Union[list[TrendRecord], L1Request, Failure]:
    missing = [c for c in SNAPSHOT_COLUMNS if c not in df.columns]
    if missing:
        return Failure(ErrorInfo(code="E_SCHEMA", message=f"listings_df is missing columns: {missing}"))
    problem = validate_criteria(effective, info)
    if problem is not None:
        return problem

    assert effective.window_end is not None
    months = window_months(effective.window_end)
    locs = sorted(set(effective.localities)) if effective.localities is not None else list(CANONICAL_LOCALITIES)

    month = rows["sale_date"].astype(str).str.slice(0, 7).to_numpy()
    locality = rows["locality"].to_numpy()
    price = rows["price"].to_numpy(dtype="float64")
    sqft = rows["sqft"].to_numpy(dtype="float64")
    valid = np.isfinite(price) & (price > 0) & (sqft > 0)  # n_in_bucket rows (data.md 5.10)
    with np.errstate(divide="ignore", invalid="ignore"):
        ppsf = price / sqft  # float64 division; only valid rows are used

    records: list[TrendRecord] = []
    for m in months:  # month ascending, ALL first, then localities alphabetically
        in_month = month == m
        for region in [ALL_REGION, *locs]:
            sel = in_month if region == ALL_REGION else in_month & (locality == region)
            use = sel & valid
            records.append(_record(m, region, int(sel.sum()), price[use], ppsf[use]))

    n_all = sum(r.listing_count for r in records if r.region_key == ALL_REGION)
    trace.step("aggregator", f"{len(records)} buckets ({len(months)} months x {1 + len(locs)} regions), "
                             f"{n_all} rows in the window", buckets=len(records), rows=n_all)
    return records
