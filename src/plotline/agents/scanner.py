"""Agent B: Scanners (contracts/Agents.md section 3).

Worker. Returns the rows of ``listings_df`` that match ``effective_criteria``,
as a new dataframe. The Planner's topology decides what B does: ``parallel``
runs one scanner per locality, ``consolidated`` runs one scanner over all of
them. Both return the same multiset of rows (I-TOPO): partitions are scanned
with the same filter and concatenated in a fixed order, never completion order.

Scanners never validate, repair, deduplicate, convert units or compute a
statistic. Invalid criteria are applied literally; the aggregator rejects them.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from plotline.contract import CANONICAL_LOCALITIES, Criteria, window_months
from plotline.state import PlanResult
from plotline.trace import TraceLog


def _mask(part: pd.DataFrame, eff: Criteria) -> pd.Series:
    assert eff.window_end is not None
    keep = part["sale_date"].str[:7].isin(window_months(eff.window_end))
    # null localities = all 7 canonical ones (contract 5.2), in both topologies
    keep &= part["locality"].isin(set(eff.localities if eff.localities is not None else CANONICAL_LOCALITIES))
    if eff.bhk is not None:
        keep &= part["bhk"].isin(set(eff.bhk))
    if eff.price_band is not None:  # inclusive, in price_unit: no unit conversion (D6)
        keep &= part["price"].between(eff.price_band[0], eff.price_band[1], inclusive="both")
    if eff.sqft_range is not None:
        keep &= part["sqft"].between(eff.sqft_range[0], eff.sqft_range[1], inclusive="both")
    if eff.sale_cond is not None:
        keep &= part["sale_cond"].isin(set(eff.sale_cond))
    return keep


def _scan_one(df: pd.DataFrame, eff: Criteria, locality: str | None) -> pd.DataFrame:
    """One scanner: its partition (one locality, or all) filtered by the criteria."""
    part = df if locality is None else df[df["locality"] == locality]
    return part[_mask(part, eff)]


def scan(plan: PlanResult, df: pd.DataFrame, trace: TraceLog) -> pd.DataFrame:
    eff = plan.effective
    if plan.topology == "parallel":
        partitions: list[str | None] = sorted(
            set(eff.localities if eff.localities is not None else CANONICAL_LOCALITIES)
        )
    else:
        partitions = [None]

    if len(partitions) > 1:
        with ThreadPoolExecutor(max_workers=len(partitions)) as pool:
            parts = list(pool.map(lambda loc: _scan_one(df, eff, loc), partitions))  # submission order
    else:
        parts = [_scan_one(df, eff, loc) for loc in partitions]

    rows = pd.concat(parts) if parts else df.iloc[0:0]
    rows = rows.copy()  # a new frame; listings_df is never handed on or modified (I-PURE)

    # one event, written after the join (TraceLog is not thread-safe)
    counts = {("all" if loc is None else loc): len(p) for loc, p in zip(partitions, parts)}
    trace.step(
        "scanner", f"scan: {len(partitions)} scanner(s), {plan.topology}: {len(rows)} rows",
        rows=len(rows), per_scanner=counts,
    )
    return rows
