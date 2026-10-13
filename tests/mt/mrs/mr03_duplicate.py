"""MR3a / MR3b, duplicate every row (contracts/Testing.md 5).

Family: invariance. Transformation: every row appears twice; the copy gets a
**new** ``listing_id`` ``<id>_dup`` (3a) or keeps the **same** ``listing_id`` (3b).
Parameters drawn: none.
Assert: ``listing_count``, ``n_in_bucket`` and ``summary.n_rows`` ×2 EXACT;
medians (REL_TOL), ``pct_change`` (ABS_TOL), ``summary.start/end`` (REL_TOL),
``change_pct`` (ABS_TOL_PCT) and flags equal. Not asserted: ``low_sample``.
Skip (either run): any ``ALL`` month with ``n_in_bucket`` ∈ {3, 4}; the pooled
first-3 or last-3 month valid-row count ∈ {3, 4} (the summary gate); ``L2_attempts`` > 0.
Targeted fault: silent dedup errors; count-weighted median corruption; the
``MIN_BUCKET_N`` gate. A 3b violation means the application dedups (breaks D3, I-NODEDUPE).
"""

from __future__ import annotations

import pandas as pd

from tests.mt.generator import Base
from tests.mt.harness import MR, Diff, FollowUp, abs_tol, exact, rel_tol
from tests.mt.mrs.common import MEDIANS, PCT, all_series, compare_flags, compare_records, compare_summary, first, \
    gate_margin, l2_skip

POOLED_MONTHS = 3  # Testing.md 5.3 / global 6.3: the summary pools the first 3 and last 3 months
TWICE = lambda n: 2 * n
FIELDS = {"listing_count": exact, "n_in_bucket": exact, **{m: rel_tol for m in MEDIANS}, PCT: abs_tol}


def duplicate(new_ids: bool):
    def transform(base: Base, df: pd.DataFrame) -> FollowUp:
        copy = df.assign(listing_id=df["listing_id"] + "_dup") if new_ids else df.copy()
        return FollowUp(base.to_criteria(), pd.concat([df, copy], ignore_index=True))  # a new frame
    return transform


def check(src: dict, fu: dict, base: Base) -> list[Diff]:
    out = compare_records(src, fu, FIELDS, expect={"listing_count": TWICE, "n_in_bucket": TWICE})
    out += compare_flags(src, fu)
    out += compare_summary(src, fu, n_rows=TWICE, direction=False)
    return out


def gate_skip(report: dict) -> str | None:
    series = all_series(report)
    if any(gate_margin(r["n_in_bucket"]) for r in series):
        return "ALL n_in_bucket in {3,4}"
    pooled = [sum(r["n_in_bucket"] for r in part)
              for part in (series[:POOLED_MONTHS], series[-POOLED_MONTHS:])]
    if any(gate_margin(n) for n in pooled):
        return "pooled first-3/last-3 count in {3,4}"
    return None


def skip(src: dict, fu: dict, base: Base) -> str | None:
    return first(gate_skip(src), gate_skip(fu), l2_skip(src, fu))


MR3a = MR(name="MR3a", family="invariance", transform=duplicate(new_ids=True), check=check, skip=skip)
MR3b = MR(name="MR3b", family="invariance", transform=duplicate(new_ids=False), check=check, skip=skip)
