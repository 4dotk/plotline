"""MR5, widen the price band (contracts/Testing.md 5).

Family: monotonic. Transformation: ``price_band`` [lo, hi] → [lo − δw, hi + δw]
with w = hi − lo. Parameters drawn: δ ∈ {0.1, 0.3} (``MR5.delta``).
Assert: ``listing_count`` in the follow-up ≥ source, for every (month, region).
Not asserted: medians.
Skip: ``price_band`` null (precondition: the transformation is undefined, never
waived); ``L2_attempts`` > 0 in either run.
Targeted fault: filter boundary defects; loop pruning dropping rows.
"""

from __future__ import annotations

import pandas as pd

from plotline.contract import Criteria
from tests.mt.generator import Base
from tests.mt.harness import MR, Diff, FollowUp
from tests.mt.mrs.common import l2_skip, records


def precondition(base: Base, df: pd.DataFrame) -> str | None:
    return "price_band null" if base.criteria["price_band"] is None else None


def transform(base: Base, df: pd.DataFrame) -> FollowUp:
    lo, hi = base.criteria["price_band"]
    pad = base.params["MR5"]["delta"] * (hi - lo)
    return FollowUp(Criteria.model_validate({**base.criteria, "price_band": [lo - pad, hi + pad]}), df.copy())


def check(src: dict, fu: dict, base: Base) -> list[Diff]:
    a, b = records(src), records(fu)
    out = [Diff(f"records.{k}", a.get(k, "<missing>"), b.get(k, "<missing>")) for k in sorted(set(a) ^ set(b))]
    out += [Diff(f"records.{k}.listing_count", a[k]["listing_count"], b[k]["listing_count"])
            for k in sorted(set(a) & set(b)) if b[k]["listing_count"] < a[k]["listing_count"]]
    return out


MR5 = MR(name="MR5", family="monotonic", transform=transform, check=check, precondition=precondition,
         skip=lambda src, fu, base: l2_skip(src, fu))
