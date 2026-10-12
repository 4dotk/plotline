"""Agent E: Anomaly Detector (contracts/Anomaly.md).

Worker. On the ``ALL`` series only (D5): month-on-month ``pct_change`` of the
median price per sqft, the ``price_jump`` and ``count_drop`` flags, and the
first-3 vs last-3 months summary pooled from the matching rows. Every threshold
is a ratio or count from section 3, so scaling prices changes no flag (I-UNIT).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from plotline.contract import (
    ALL_REGION,
    ANOMALY_PCT,
    COUNT_DROP,
    FLAT_BAND_PCT,
    MIN_BUCKET_N,
    AnomalyFlag,
    Criteria,
    StatChange,
    Summary,
    TrendRecord,
    window_months,
)
from plotline.state import Analysis
from plotline.trace import TraceLog

SUMMARY_MONTHS = 3  # first 3 vs last 3 months (CONTRACT.md 6.1)


def _median(values: np.ndarray) -> float:
    return float(np.median(np.sort(values)))  # sorted values (I-ORDER)


def _stat_change(start: float, end: float) -> StatChange:
    change = (end / start - 1) * 100
    direction = "up" if change > FLAT_BAND_PCT else "down" if change < -FLAT_BAND_PCT else "flat"
    return StatChange(start=start, end=end, change_pct=change, direction=direction)


def _summary(rows: pd.DataFrame, effective: Criteria) -> Summary:
    assert effective.window_end is not None
    months = window_months(effective.window_end)
    month = rows["sale_date"].astype(str).str.slice(0, 7).to_numpy()
    in_window = np.isin(month, months)
    price = rows["price"].to_numpy(dtype="float64")
    sqft = rows["sqft"].to_numpy(dtype="float64")
    valid = in_window & np.isfinite(price) & (price > 0) & (sqft > 0)
    first = valid & np.isin(month, months[:SUMMARY_MONTHS])
    last = valid & np.isin(month, months[-SUMMARY_MONTHS:])
    n_rows = int(in_window.sum())
    if first.sum() < MIN_BUCKET_N or last.sum() < MIN_BUCKET_N:
        return Summary(n_rows=n_rows, price=None, price_per_sqft=None)
    ppsf = np.divide(price, sqft, out=np.full_like(price, np.nan), where=sqft > 0)
    return Summary(
        n_rows=n_rows,
        price=_stat_change(_median(price[first]), _median(price[last])),
        price_per_sqft=_stat_change(_median(ppsf[first]), _median(ppsf[last])),
    )


def analyse(records: list[TrendRecord], rows: pd.DataFrame, effective: Criteria, trace: TraceLog) -> Analysis:
    all_series = sorted((r for r in records if r.region_key == ALL_REGION), key=lambda r: r.month)
    pct: dict[str, float] = {}
    flags: list[AnomalyFlag] = []
    for prev, cur in zip(all_series, all_series[1:]):  # the first month is never flagged
        prev_ok = prev.n_in_bucket >= MIN_BUCKET_N
        if prev_ok and cur.n_in_bucket >= MIN_BUCKET_N:
            assert prev.median_price_per_sqft is not None and cur.median_price_per_sqft is not None
            change = cur.median_price_per_sqft / prev.median_price_per_sqft - 1
            pct[cur.month] = change
            if abs(change) > ANOMALY_PCT:  # strictly greater
                verb = "rose" if change > 0 else "fell"
                flags.append(AnomalyFlag(
                    month=cur.month, region_key=ALL_REGION, kind="price_jump", value=change,
                    threshold=ANOMALY_PCT,
                    reason=f"median price per sqft {verb} {abs(change) * 100:.1f}% vs {prev.month}",
                ))
        if prev_ok and cur.listing_count <= COUNT_DROP * prev.listing_count:
            ratio = cur.listing_count / prev.listing_count
            flags.append(AnomalyFlag(
                month=cur.month, region_key=ALL_REGION, kind="count_drop", value=ratio, threshold=COUNT_DROP,
                reason=f"listing count fell to {cur.listing_count} from {prev.listing_count} in {prev.month}",
            ))

    out = [r.model_copy(update={"pct_change_price_per_sqft": pct[r.month]})
           if r.region_key == ALL_REGION and r.month in pct else r for r in records]
    summary = _summary(rows, effective)
    trace.step("anomaly", f"{len(flags)} flag(s); summary over {summary.n_rows} rows",
               flags=[f"{f.month}:{f.kind}" for f in flags])
    return Analysis(records=out, flags=flags, summary=summary)
