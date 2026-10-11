"""Stub agents A, B, C, D, E, G.

Each stub returns a *contract-valid* but empty result so the whole pipeline can
run end to end before the real agents exist. A stub is replaced by passing its
real counterpart in ``AgentSet``; nothing else changes.

What the stubs do (and do not do):
  A plan      : real defaults and topology rule (shared with the planner); no sentence
                parsing, no L1 repair.
  B scan      : returns no rows (empty copy of the input).
  C aggregate : real dense grid (all buckets empty); real L1 issue detection.
  D validate  : real coverage count; never fires L2 (logs why).
  E analyse   : no pct change, no flags; summary with the right ``n_rows`` and null stats.
  G diagnose  : template text from each flag's reason (none in practice).
"""

from __future__ import annotations

from typing import Union

import pandas as pd

from plotline.agents.planner import with_topology
from plotline.contract import (
    ALL_REGION,
    CANONICAL_LOCALITIES,
    COVERAGE_MIN_MONTHS,
    MIN_BUCKET_N,
    WINDOW_MONTHS,
    AnomalyFlag,
    Criteria,
    Diagnostic,
    ErrorInfo,
    LlmMode,
    RunOptions,
    Summary,
    TrendRecord,
    window_months,
)
from plotline.state import (
    AgentSet,
    Analysis,
    CoverageDecision,
    DataInfo,
    Failure,
    L1Request,
    PlanResult,
    SNAPSHOT_COLUMNS,
)
from plotline.trace import TraceLog

_ISSUE_FIELD = {
    "band_inverted": "price_band",
    "locality_unknown": "localities",
    "window_out_of_range": "window_end",
    "bhk_out_of_range": "bhk",
    "sale_cond_unknown": "sale_cond",
}


# -- A: Query Planner ---------------------------------------------------------


def plan(query, info: DataInfo, options: RunOptions, seed: int, llm_mode: LlmMode, trace: TraceLog, llm=None):
    if isinstance(query, str):  # AI mode: the stub cannot parse a sentence
        if llm_mode == "off":
            return Failure(ErrorInfo(code="E_LLM_OFF", message="AI mode requested with LLM_MODE=off"))
        return Failure(
            ErrorInfo(code="E_NL_UNPARSEABLE", message="stub planner cannot parse a sentence")
        )
    effective = query.model_copy(deep=True)
    if effective.window_end is None:
        effective.window_end = info.latest_month  # D2: default = latest month
    return with_topology(effective, query, options, trace)


def repair(plan_: PlanResult, request: L1Request, info: DataInfo, options: RunOptions, l1_repairs: int, trace: TraceLog):
    field = request.fields[0] if request.fields else "criteria"
    return Failure(
        ErrorInfo(code="E_INVALID_CRITERIA", message=f"invalid {field}: {request.issues} (stub planner does not repair)")
    )


# -- B: Scanners --------------------------------------------------------------


def scan(plan_: PlanResult, df: pd.DataFrame, trace: TraceLog) -> pd.DataFrame:
    trace.step("scanner", f"{plan_.n_scanners} scanner(s), {plan_.topology}: 0 rows (stub)")
    return df.iloc[0:0].copy()


# -- C: Result Aggregator -----------------------------------------------------


def aggregate(effective: Criteria, rows: pd.DataFrame, df: pd.DataFrame, info: DataInfo, trace: TraceLog):
    missing = [c for c in SNAPSHOT_COLUMNS if c not in df.columns]
    if missing:
        return Failure(ErrorInfo(code="E_SCHEMA", message=f"listings_df is missing columns: {missing}"))

    issues = list(effective.domain_violations())
    assert effective.window_end is not None
    if not info.first_valid_end <= effective.window_end <= info.latest_month:
        issues.append("window_out_of_range")
    if issues:
        return L1Request(issues=issues, fields=[_ISSUE_FIELD[i] for i in issues])

    locs = sorted(set(effective.localities)) if effective.localities is not None else list(CANONICAL_LOCALITIES)
    records = [
        TrendRecord(
            month=m, region_key=region, listing_count=0, n_in_bucket=0, median_price=None,
            median_price_per_sqft=None, low_sample=True, pct_change_price_per_sqft=None,
        )
        for m in window_months(effective.window_end)
        for region in [ALL_REGION, *locs]  # month asc, ALL first, localities alphabetical
    ]
    trace.step("aggregator", f"{len(records)} buckets (dense grid, stub counts)")
    return records


# -- D: Coverage Validator ----------------------------------------------------


def validate(records, effective, original, options, l2_attempts, llm_mode, seed, trace: TraceLog, llm=None):
    covered = sum(1 for r in records if r.region_key == ALL_REGION and r.n_in_bucket >= MIN_BUCKET_N)
    decision = CoverageDecision(coverage_months=covered, coverage_score=covered / WINDOW_MONTHS)
    if covered >= COVERAGE_MIN_MONTHS:
        return decision
    has_soft = any(v is not None for v in (original.price_band, original.sqft_range, original.sale_cond))
    if not options.loops_enabled:
        trace.l2_disabled()
    elif not has_soft:
        trace.l2_skipped()
    else:
        trace.warning("validator", "stub validator does not widen; continuing with low coverage")
    return decision


# -- E: Anomaly Detector ------------------------------------------------------


def analyse(records, rows, effective, trace: TraceLog) -> Analysis:
    n_rows = sum(r.listing_count for r in records if r.region_key == ALL_REGION)
    trace.step("anomaly", "no anomaly analysis (stub)")
    return Analysis(records=records, flags=[], summary=Summary(n_rows=n_rows, price=None, price_per_sqft=None))


# -- G: Diagnostic ------------------------------------------------------------


def diagnose(flags: list[AnomalyFlag], records, llm_mode: LlmMode, seed: int, trace: TraceLog):
    return [Diagnostic(month=f.month, text=f.reason, source="template") for f in flags]


def stub_agents() -> AgentSet:
    return AgentSet(
        plan=plan, repair=repair, scan=scan, aggregate=aggregate,
        validate=validate, analyse=analyse, diagnose=diagnose,
    )
