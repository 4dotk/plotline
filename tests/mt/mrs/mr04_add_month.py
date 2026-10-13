"""MR4, add X to every price in one month (contracts/Testing.md 5).

Family: monotonic. Transformation: +X on ``price`` of every row sold in window
month m. Parameters drawn: X ∈ {250,000; 1,000,000} and m (``MR4.X``, ``MR4.month``).
Assert: month m, every region: ``median_price`` = source + X (REL_TOL), counts
EXACT. Every month ≠ m: all record fields equal, except ``pct_change`` at m+1.
Flags equal outside months m and m+1. No month's ``median_price`` decreases.
Not asserted: month m ``median_price_per_sqft``; ``pct_change`` and flags of
months m and m+1; ``summary``.
Skip: ``price_band`` set (``effective_criteria``, either run); ``ALL``
``n_in_bucket(m)`` < ``MIN_BUCKET_N`` (either run).
Targeted fault: cross-bucket record leakage in monthly aggregation.
"""

from __future__ import annotations

import pandas as pd

from plotline.contract import MIN_BUCKET_N, month_add
from tests.mt.generator import Base
from tests.mt.harness import MR, Diff, FollowUp, exact, rel_tol
from tests.mt.mrs.common import ALL, PCT, RECORD_CMP, all_reasons, compare_flags, compare_records, month_of, records


def params(base: Base) -> tuple[int, str]:
    p = base.params["MR4"]
    return p["X"], p["month"]


def transform(base: Base, df: pd.DataFrame) -> FollowUp:
    x, m = params(base)
    in_m = df["sale_date"].astype(str).str.slice(0, 7) == m
    return FollowUp(base.to_criteria(), df.assign(price=df["price"].where(~in_m, df["price"] + x)))  # a new frame


def check(src: dict, fu: dict, base: Base) -> list[Diff]:
    x, m = params(base)
    after = month_add(m, 1)
    a, b = records(src), records(fu)
    in_m = [k for k in a if month_of(k) == m]
    out = compare_records(src, fu, {"listing_count": exact, "n_in_bucket": exact, "median_price": rel_tol},
                          expect={"median_price": lambda v: v + x}, keys=in_m)
    out += compare_records(src, fu, RECORD_CMP, keys=sorted((set(a) | set(b)) - set(in_m)),
                           skip_field=lambda k, f: f == PCT and month_of(k) == after)
    for k in sorted(set(a) & set(b)):
        s, f = a[k]["median_price"], b[k]["median_price"]
        if s is not None and f is not None and f < s and not rel_tol(s, f):
            out.append(Diff(f"records.{k}.median_price decreased", s, f))
    months = {month_of(k) for k in a} - {m, after}
    out += compare_flags(src, fu, months)
    return out


def skip(src: dict, fu: dict, base: Base) -> str | None:
    _, m = params(base)

    def one(report: dict) -> str | None:
        if report["effective_criteria"]["price_band"] is not None:
            return "price_band set"
        if records(report)[f"{m}/{ALL}"]["n_in_bucket"] < MIN_BUCKET_N:
            return "ALL n_in_bucket(m) < MIN_BUCKET_N"
        return None

    return all_reasons(one(src), one(fu))


MR4 = MR(name="MR4", family="monotonic", transform=transform, check=check, skip=skip)
