"""Executable reference for GLOBAL_CONTRACT.md formulas.

ALL series only; no agent loops.

Usage:
    python scripts/golden_vectors.py data/chennai_snapshot.csv
    python scripts/golden_vectors.py data/chennai_snapshot.csv 2015-02 2011-12

The default run prints the reference windows in the contract.
The application logic and independent test oracle must reproduce them.
"""

import sys

import numpy as np
import pandas as pd


MIN_BUCKET_N = 5
COVERAGE_MIN_BUCKETS = 9
WINDOW_MONTHS = 12
ANOMALY_PCT = 0.12
COUNT_DROP = 0.50
FLAT_BAND = 0.01

DEFAULT_WINDOWS = ("2015-02", "2011-12")


def run_all_series(df: pd.DataFrame, window_end: str):
    """Calculate the 12-month ALL-series reference results."""

    required = {"sale_date", "price", "sqft"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Snapshot missing required columns: {sorted(missing)}")

    end = pd.Period(window_end, freq="M")
    months = pd.period_range(
        end - (WINDOW_MONTHS - 1), end, freq="M"
    )

    d = df.copy()
    d["month"] = pd.PeriodIndex(
        pd.to_datetime(d["sale_date"], errors="raise").dt.strftime("%Y-%m"),
        freq="M",
    )
    d = d[d["month"].isin(months)].copy()

    # Invalid or missing values must not silently enter the calculations.
    d["price"] = pd.to_numeric(d["price"], errors="raise")
    d["sqft"] = pd.to_numeric(d["sqft"], errors="raise")

    if d[["price", "sqft"]].isna().any().any():
        raise ValueError("Missing price or sqft values in the selected window")
    if (d["sqft"] <= 0).any():
        raise ValueError("sqft must be positive to calculate price per sqft")

    d["ppsf"] = d["price"] / d["sqft"]

    records = []
    for month in months:
        group = d[d["month"] == month]
        n = len(group)

        records.append(
            {
                "month": str(month),
                "listing_count": n,
                "n_in_bucket": n,
                "median_price": (
                    float(np.median(group["price"])) if n else np.nan
                ),
                "median_ppsf": (
                    float(np.median(group["ppsf"])) if n else np.nan
                ),
            }
        )

    result = pd.DataFrame(records)
    result["pct"] = np.nan
    flags = []

    for i in range(1, len(result)):
        previous = result.iloc[i - 1]
        current = result.iloc[i]

        previous_n = int(previous["n_in_bucket"])
        current_n = int(current["n_in_bucket"])

        # Price-per-square-foot anomaly: both adjacent buckets need
        # sufficient samples.
        if previous_n >= MIN_BUCKET_N and current_n >= MIN_BUCKET_N:
            previous_ppsf = previous["median_ppsf"]
            current_ppsf = current["median_ppsf"]

            pct = current_ppsf / previous_ppsf - 1
            result.loc[i, "pct"] = pct

            if abs(pct) > ANOMALY_PCT:
                flags.append(
                    (current["month"], "price_jump", round(float(pct), 4))
                )

        # Count-drop anomaly, measured against the previous month.
        if (
            previous_n >= MIN_BUCKET_N
            and current_n <= COUNT_DROP * previous["listing_count"]
        ):
            ratio = (
                current["listing_count"] / previous["listing_count"]
                if previous["listing_count"]
                else np.nan
            )
            flags.append(
                (current["month"], "count_drop", round(float(ratio), 4))
            )

    qualifying_months = int(
        (result["n_in_bucket"] >= MIN_BUCKET_N).sum()
    )
    coverage = qualifying_months / WINDOW_MONTHS
    coverage_pass = qualifying_months >= COVERAGE_MIN_BUCKETS

    first_months = set(months[:3])
    last_months = set(months[-3:])

    first = d[d["month"].isin(first_months)]
    last = d[d["month"].isin(last_months)]

    summary = {}
    for column, name in (
        ("price", "price"),
        ("ppsf", "price_per_sqft"),
    ):
        # Do not calculate misleading medians for empty periods.
        if first.empty or last.empty:
            summary[name] = {
                "start": None,
                "end": None,
                "change_pct": None,
                "direction": None,
            }
            continue

        start = float(np.median(first[column]))
        finish = float(np.median(last[column]))

        if start == 0:
            change_pct = None
            direction = None
        else:
            change = finish / start - 1
            change_pct = change * 100
            direction = (
                "flat"
                if abs(change) <= FLAT_BAND
                else ("up" if change > 0 else "down")
            )

        summary[name] = {
            "start": start,
            "end": finish,
            "change_pct": change_pct,
            "direction": direction,
        }

    return result, coverage, coverage_pass, flags, summary, len(d)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage: python scripts/golden_vectors.py "
            "data/chennai_snapshot.csv [WINDOW_END ...]"
        )

    snapshot_path = sys.argv[1]
    window_ends = sys.argv[2:] or list(DEFAULT_WINDOWS)

    df = pd.read_csv(snapshot_path)

    for window_end in window_ends:
        result, coverage, coverage_pass, flags, summary, row_count = (
            run_all_series(df, window_end)
        )

        print(
            f"\n=== window_end {window_end}: rows {row_count}, "
            f"coverage {coverage:.4f}, coverage_pass {coverage_pass}"
        )
        print(
            result.to_string(
                index=False,
                float_format=lambda value: f"{value:.4f}",
                na_rep="NaN",
            )
        )
        print("flags  :", flags)

        for name, values in summary.items():
            if values["change_pct"] is None:
                print(f"summary {name}: unavailable (empty period or zero baseline)")
            else:
                print(
                    f"summary {name}: "
                    f"start {values['start']:.4f} "
                    f"end {values['end']:.4f} "
                    f"change {values['change_pct']:.4f}% "
                    f"{values['direction']}"
                )


if __name__ == "__main__":
    main()
