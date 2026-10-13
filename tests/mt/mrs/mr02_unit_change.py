"""MR2, unit change (contracts/Testing.md 5).

Family: invariance. Transformation: ``price`` and ``price_band`` ÷ 100,000 and
``price_unit = "lakh"``. Parameters drawn: none.
Assert: counts, ``low_sample``, flags, ``coverage_score``, ``summary.n_rows`` and
``direction`` EXACT; ``median_price``, ``median_price_per_sqft`` and
``summary.start/end`` equal source ÷ 100,000 (REL_TOL); ``pct_change`` (ABS_TOL)
and ``change_pct`` (ABS_TOL_PCT) equal. Not asserted: the ``price_unit`` string.
Skip: flag margin, any ``||pct| − ANOMALY_PCT| < 1e-9``, in either run.
Targeted fault: hard-coded unit assumptions; absolute thresholds in anomaly detection.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

from plotline.contract import Criteria
from tests.mt.generator import Base
from tests.mt.harness import MR, Diff, FollowUp, diff, exact
from tests.mt.mrs.common import RECORD_CMP, compare_flags, compare_records, compare_summary, first, flag_margin

INR_PER_LAKH = 100_000  # contract 5.2 (a unit, not a tolerance)


def scale_check(factor: Callable[[Base], float]) -> Callable[[dict, dict, Base], list[Diff]]:
    """The MR2 / MR8 assertion: every money field × ``factor``, everything else unchanged."""

    def check(src: dict, fu: dict, base: Base) -> list[Diff]:
        k = factor(base)
        times_k = lambda x: x * k
        out = compare_records(src, fu, RECORD_CMP, expect={"median_price": times_k, "median_price_per_sqft": times_k})
        out += compare_flags(src, fu)
        out += diff(src["coverage_score"], fu["coverage_score"], exact, "coverage_score")
        out += compare_summary(src, fu, scale=times_k)
        return out

    return check


def flag_margin_skip(src: dict, fu: dict, base: Base) -> str | None:
    return first(flag_margin(src), flag_margin(fu))


def transform(base: Base, df: pd.DataFrame) -> FollowUp:
    out = df.assign(price=df["price"] / INR_PER_LAKH)  # a new frame
    band = base.criteria["price_band"]
    criteria = {**base.criteria, "price_unit": "lakh",
                "price_band": None if band is None else [v / INR_PER_LAKH for v in band]}
    return FollowUp(Criteria.model_validate(criteria), out)


MR2 = MR(name="MR2", family="invariance", transform=transform,
         check=scale_check(lambda base: 1 / INR_PER_LAKH), skip=flag_margin_skip)
