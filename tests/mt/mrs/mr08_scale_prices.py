"""MR8, scale prices by k (contracts/Testing.md 5).

Family: directional. Transformation: ``price`` and ``price_band`` × k
(``price_unit`` unchanged). Parameters drawn: k ∈ {2, 4, 10} (``MR8.k``).
Assert: as MR2 with the factor k: counts, flags, ``coverage_score``,
``direction`` EXACT; medians and ``summary.start/end`` equal source × k
(REL_TOL); ``pct_change`` (ABS_TOL) and ``change_pct`` (ABS_TOL_PCT) equal.
Skip: flag margin as in MR2, in either run.
Targeted fault: absolute anomaly thresholds firing under scale.
"""

from __future__ import annotations

import pandas as pd

from plotline.contract import Criteria
from tests.mt.generator import Base
from tests.mt.harness import MR, FollowUp
from tests.mt.mrs.mr02_unit_change import flag_margin_skip, scale_check


def k_of(base: Base) -> int:
    return base.params["MR8"]["k"]


def transform(base: Base, df: pd.DataFrame) -> FollowUp:
    k = k_of(base)
    out = df.assign(price=df["price"] * k)  # a new frame
    band = base.criteria["price_band"]
    criteria = {**base.criteria, "price_band": None if band is None else [v * k for v in band]}
    return FollowUp(Criteria.model_validate(criteria), out)


MR8 = MR(name="MR8", family="directional", transform=transform, check=scale_check(k_of), skip=flag_margin_skip)
