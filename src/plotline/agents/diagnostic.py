"""Agent G: Diagnostic (contracts/Diagnostic.md).

Text writer, for the UI only: a short plain-language reason for each anomaly
flag. It may change ``diagnostics`` and nothing else (I-LLM), and no test of a
number depends on it (the comparators ignore ``diagnostics``).

  * ``LLM_MODE=off``       template text, ``source = "template"``, no model call;
  * ``live`` / ``replay``  one call per flag through ``llm_client``; the figures in
                           the prompt come from code, the model writes words only;
  * malformed output       one ``warning`` per failed attempt, then the template for
                           that flag (a fallback never fails the run);
  * replay miss            ``E_REPLAY_MISS`` (LLM.md clarification 8).

No flags means no entries and no model call.
"""

from __future__ import annotations

from typing import Union

from pydantic import BaseModel, ConfigDict, StrictStr, field_validator

from plotline.contract import (
    ALL_REGION,
    AnomalyFlag,
    Diagnostic,
    ErrorInfo,
    LlmMode,
    TrendRecord,
    canonical_json,
    month_add,
)
from plotline.llm_client import LlmSession, load_prompt
from plotline.state import Failure
from plotline.trace import TraceLog


class DiagnosticText(BaseModel):
    """The only answer the model may give (LLM.md 7): one non-empty ``text``."""

    model_config = ConfigDict(extra="forbid", strict=True)
    text: StrictStr

    @field_validator("text")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be empty")
        return v.strip()


def template_text(flag: AnomalyFlag) -> str:
    """Deterministic text: the flag's own reason (built from its numbers by agent E)."""
    return flag.reason


def _figures(rec: TrendRecord | None) -> dict | None:
    if rec is None:
        return None
    return {
        "month": rec.month,
        "sales": rec.listing_count,
        "sales_with_usable_price": rec.n_in_bucket,
        "median_price_per_sqft": rec.median_price_per_sqft,
        "median_price": rec.median_price,
    }


def user_prompt(flag: AnomalyFlag, by_month: dict[str, TrendRecord]) -> str:
    """Figures for one flag, passed in from code (canonical JSON, so it is stable)."""
    return canonical_json({
        "flag": {"month": flag.month, "kind": flag.kind, "value": flag.value, "threshold": flag.threshold},
        "this_month": _figures(by_month.get(flag.month)),
        "previous_month": _figures(by_month.get(month_add(flag.month, -1))),
    })


def diagnose(
    flags: list[AnomalyFlag], records: list[TrendRecord], llm_mode: LlmMode, seed: int,
    trace: TraceLog, llm: LlmSession | None = None,
) -> Union[list[Diagnostic], Failure]:
    if not flags:
        return []  # nothing to explain, so no model call
    if llm_mode == "off" or llm is None:
        return [Diagnostic(month=f.month, text=template_text(f), source="template") for f in flags]

    by_month = {r.month: r for r in records if r.region_key == ALL_REGION}
    system = load_prompt("diagnostic")
    out_list: list[Diagnostic] = []
    for flag in flags:
        out = llm.call("diagnostic", system, user_prompt(flag, by_month), DiagnosticText)
        if out.replay_miss:
            return Failure(ErrorInfo(code="E_REPLAY_MISS", message="diagnostic prompt is not in the replay cache"))
        for failure in out.failures:
            trace.warning("diagnostic", f"{flag.month} {flag.kind}: {failure}")
        if out.value is not None:
            assert isinstance(out.value, DiagnosticText)
            out_list.append(Diagnostic(month=flag.month, text=out.value.text, source="llm"))
        else:
            trace.warning("diagnostic", f"fallback: template text for {flag.month} {flag.kind}; model output unusable")
            out_list.append(Diagnostic(month=flag.month, text=template_text(flag), source="template"))
    return out_list
