"""MR7, shift the window by one month (contracts/Testing.md 5).

Family: directional (the assignment's label); in substance an **invariance on
the overlap**. Transformation: ``window_end`` + 1 month. Parameters drawn: none.
With source months m1…m12 and follow-up m2…m13:
Assert: the 11 overlap months m2…m12, every region: all record fields equal,
except ``pct_change``, which (with the flags) is compared only on m3…m12.
Not asserted: ``coverage_score``, ``summary``, ``n_rows``.
Skip: ``window_end`` + 1 beyond the snapshot (precondition: the transformation is
undefined, never waived); ``L2_attempts`` > 0 in either run.
Targeted fault: temporal boundary conditions; off-by-one window maths;
window-wide state (coverage, L2).
"""

from __future__ import annotations

import pandas as pd

from plotline.contract import Criteria, month_add, window_months
from tests.mt.generator import Base, valid_window_ends
from tests.mt.harness import MR, Diff, FollowUp
from tests.mt.mrs.common import PCT, RECORD_CMP, compare_flags, compare_records, l2_skip, month_of, records


def precondition(base: Base, df: pd.DataFrame) -> str | None:
    if month_add(base.criteria["window_end"], 1) > valid_window_ends(df)[-1]:
        return "window_end + 1 beyond the snapshot"
    return None


def transform(base: Base, df: pd.DataFrame) -> FollowUp:
    end = month_add(base.criteria["window_end"], 1)
    return FollowUp(Criteria.model_validate({**base.criteria, "window_end": end}), df.copy())


def check(src: dict, fu: dict, base: Base) -> list[Diff]:
    overlap = window_months(base.criteria["window_end"])[1:]  # m2…m12
    m2 = overlap[0]
    keys = sorted(k for k in set(records(src)) | set(records(fu)) if month_of(k) in overlap)
    out = compare_records(src, fu, RECORD_CMP, keys=keys, skip_field=lambda k, f: f == PCT and month_of(k) == m2)
    out += compare_flags(src, fu, overlap[1:])  # m3…m12
    return out


MR7 = MR(name="MR7", family="directional", transform=transform, check=check, precondition=precondition,
         skip=lambda src, fu, base: l2_skip(src, fu))
