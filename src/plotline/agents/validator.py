"""Agent D: Coverage Validator (contracts/Validator.md).

Decision-maker. Counts the covered months of the ``ALL`` series and, when
coverage is low, decides loop L2: widen the soft filters and rescan, or stop.
With ``LLM_MODE=off`` the rule is ``widen``; otherwise the model chooses
``widen`` or ``stop`` from counts and filter names only, never a price, sqft or
locality value (so MR1, MR2 and MR8 leave the prompt unchanged).

Widening is always measured from the criteria as validated (after L1), never
cumulatively, and touches only the soft filters (D7).
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, ConfigDict

from plotline.contract import (
    ALL_REGION,
    COVERAGE_MIN_MONTHS,
    L2_CAP,
    L2_WIDEN,
    MIN_BUCKET_N,
    WINDOW_MONTHS,
    Criteria,
    ErrorInfo,
    LlmMode,
    RunOptions,
    TrendRecord,
    canonical_json,
)
from plotline.llm_client import LlmSession, load_prompt
from plotline.state import CoverageDecision, Failure
from plotline.trace import TraceLog

SOFT_FILTERS = ("price_band", "sqft_range", "sale_cond")  # D7


class L2Choice(BaseModel):
    """The only answer the model may give (LLM.md 7)."""

    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["widen", "stop"]


def coverage_months(records: list[TrendRecord]) -> int:
    return sum(1 for r in records if r.region_key == ALL_REGION and r.n_in_bucket >= MIN_BUCKET_N)


def soft_filters_set(criteria: Criteria) -> list[str]:
    return [name for name in SOFT_FILTERS if getattr(criteria, name) is not None]


def _widen_range(rng: list, factor: float) -> list:
    lo, hi = rng
    width = hi - lo
    return [max(lo - factor * width, 0), hi + factor * width]


def widen(original: Criteria, factor: float | str) -> Criteria:
    """Soft filters of ``original`` widened by one ``L2_WIDEN`` step."""
    if factor == "drop":
        return original.model_copy(deep=True, update={name: None for name in SOFT_FILTERS})
    update = {
        name: _widen_range(getattr(original, name), float(factor))
        for name in ("price_band", "sqft_range") if getattr(original, name) is not None
    }  # sale_cond is not a range: unchanged until the "drop" step (Agents.md clarification 2)
    return original.model_copy(deep=True, update=update)


def decision_prompt(covered: int, attempt: int, soft: list[str]) -> str:
    """Counts and names only."""
    return canonical_json({
        "coverage_months": covered, "need_months": COVERAGE_MIN_MONTHS, "attempt": attempt,
        "cap": L2_CAP, "soft_filters": soft, "next_factor": L2_WIDEN[attempt - 1],
    })


def validate(
    records: list[TrendRecord], effective: Criteria, original: Criteria, options: RunOptions,
    l2_attempts: int, llm_mode: LlmMode, seed: int, trace: TraceLog, llm: LlmSession | None = None,
) -> Union[CoverageDecision, Failure]:
    covered = coverage_months(records)
    decision = CoverageDecision(coverage_months=covered, coverage_score=covered / WINDOW_MONTHS)
    if covered >= COVERAGE_MIN_MONTHS:  # the integer test, never the float (D4)
        trace.decision("validator", f"coverage {covered}/{WINDOW_MONTHS} meets {COVERAGE_MIN_MONTHS}/{WINDOW_MONTHS}")
        return decision

    soft = soft_filters_set(original)
    if not options.loops_enabled:
        trace.l2_disabled()
        return decision
    if not soft:
        trace.l2_skipped()
        return decision
    if l2_attempts >= L2_CAP:
        trace.decision("validator", f"L2 cap reached: coverage {covered}/{WINDOW_MONTHS} after {L2_CAP} attempts")
        return decision

    attempt = l2_attempts + 1
    action, decided_by = "widen", "rule"
    if llm_mode != "off" and llm is not None:
        out = llm.call("validator", load_prompt("validator"), decision_prompt(covered, attempt, soft), L2Choice)
        if out.replay_miss:
            return Failure(ErrorInfo(code="E_REPLAY_MISS", message="validator prompt is not in the replay cache"))
        for failure in out.failures:
            trace.warning("validator", failure)
        if out.value is not None:
            assert isinstance(out.value, L2Choice)
            action, decided_by = out.value.action, "llm"
        else:
            trace.warning("validator", "fallback: the rule (widen); model output unusable")

    if action == "stop":
        trace.l2_stopped_by_model(covered)  # a decision, not a loop firing
        return decision

    widened = widen(original, L2_WIDEN[attempt - 1])
    trace.l2_fired(covered, attempt, widened.price_band, decided_by)
    decision.widen_to = widened
    return decision
