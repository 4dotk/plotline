"""MR10, partition by BHK: the per-BHK counts add up (contracts/Testing.md 5).

Family: monotonic (additive). Transformation: ``bhk`` null (all of ``BHK_VALUES``)
or set B → one follow-up run per value b ∈ B with ``bhk = [b]``. Parameters drawn: none.
Assert: Σ over b of ``listing_count`` = source ``listing_count``, per (month,
region), EXACT. Not asserted: medians.
Skip: ``L2_attempts`` > 0 in any run; any soft filter (``price_band``,
``sqft_range``, ``sale_cond``) set in any run's ``effective_criteria``.
Targeted fault: filter or partition defects; rows lost or double-counted across BHK.
"""

from __future__ import annotations

import pandas as pd

from plotline.contract import BHK_VALUES, Criteria
from tests.mt.generator import Base
from tests.mt.harness import MR, Diff, FollowUp
from tests.mt.mrs.common import first, l2_skip, records

SOFT = ("price_band", "sqft_range", "sale_cond")


def partition(base: Base) -> list[int]:
    return list(base.criteria["bhk"] or BHK_VALUES)


def transform(base: Base, df: pd.DataFrame) -> list[FollowUp]:
    return [FollowUp(Criteria.model_validate({**base.criteria, "bhk": [b]}), df.copy()) for b in partition(base)]


def check(src: dict, fus: list[dict], base: Base) -> list[Diff]:
    a, parts = records(src), [records(f) for f in fus]
    out: list[Diff] = []
    for k in sorted(set(a).union(*parts)):
        if k not in a or any(k not in p for p in parts):
            out.append(Diff(f"records.{k}", a.get(k, "<missing>"), [p.get(k, "<missing>") for p in parts]))
            continue
        total = sum(p[k]["listing_count"] for p in parts)
        if total != a[k]["listing_count"]:
            out.append(Diff(f"records.{k}.listing_count", a[k]["listing_count"],
                            {b: p[k]["listing_count"] for b, p in zip(partition(base), parts)}))
    return out


def skip(src: dict, fus: list[dict], base: Base) -> str | None:
    soft = next((f for r in (src, *fus) for f in SOFT if r["effective_criteria"][f] is not None), None)
    return first(l2_skip(src, *fus), None if soft is None else f"soft filter set ({soft})")


MR10 = MR(name="MR10", family="monotonic", transform=transform, check=check, skip=skip)
