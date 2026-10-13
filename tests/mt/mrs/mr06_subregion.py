"""MR6, restrict localities to a sub-region (contracts/Testing.md 5).

Family: monotonic. Transformation: ``localities`` L → a proper non-empty subset
S ⊂ L (L null = all 7). Parameters drawn: S (``MR6.subset``).
Assert: ``ALL.listing_count(S) ≤ ALL.listing_count(L)`` per month; the locality
records for l ∈ S equal in both runs (EXACT / REL_TOL / ABS_TOL by field).
Not asserted: ``coverage_score``.
Skip: |L| < 2 (precondition: no proper non-empty subset, never waived);
``L2_attempts`` > 0 in either run.
Targeted fault: topology double-counting between parallel and merged workers.
"""

from __future__ import annotations

import pandas as pd

from plotline.contract import Criteria
from tests.mt.generator import Base
from tests.mt.harness import MR, Diff, FollowUp
from tests.mt.mrs.common import ALL, RECORD_CMP, compare_records, l2_skip, records, region_of


def precondition(base: Base, df: pd.DataFrame) -> str | None:
    return "|L| < 2" if base.params["MR6"]["subset"] is None else None


def transform(base: Base, df: pd.DataFrame) -> FollowUp:
    return FollowUp(Criteria.model_validate({**base.criteria, "localities": base.params["MR6"]["subset"]}), df.copy())


def check(src: dict, fu: dict, base: Base) -> list[Diff]:
    a, b = records(src), records(fu)
    out: list[Diff] = []
    for k in sorted(k for k in a if region_of(k) == ALL):
        if k not in b:
            out.append(Diff(f"records.{k}", a[k], "<missing>"))
        elif b[k]["listing_count"] > a[k]["listing_count"]:
            out.append(Diff(f"records.{k}.listing_count", a[k]["listing_count"], b[k]["listing_count"]))
    subset = set(base.params["MR6"]["subset"])
    out += compare_records(src, fu, RECORD_CMP, keys=sorted(k for k in set(a) | set(b) if region_of(k) in subset))
    extra = sorted(k for k in b if region_of(k) not in subset | {ALL})  # a region outside S in the follow-up
    out += [Diff(f"records.{k}", "<missing>", b[k]) for k in extra]
    return out


MR6 = MR(name="MR6", family="monotonic", transform=transform, check=check, precondition=precondition,
         skip=lambda src, fu, base: l2_skip(src, fu))
