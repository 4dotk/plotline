"""Agent H: Inspector (contract 1.2.0).

Worker. Knows what the data holds (``DataInfo``: the month range and, per
locality, its own months and BHK values) and checks every request against it.

  * before the scan: a request the data cannot hold as asked (a window outside
    the data, a BHK outside 1-4, an inverted band, a place that is not one of
    the 7 localities) goes back to the Planner as an L1 request; nothing the
    Planner cannot repair is answered;
  * at the end: one plain notice per thing the user must know about how the
    question was answered: each L1 repair, an L2 widening, a filter the
    sentence mentions but the criteria lack, and every requested locality that
    has no sales for the hard filters (locality, window, BHK), with what that
    locality does hold. No repair and no empty answer is invisible.

It never changes the criteria and never talks to D, E or G. Text comes from
templates; every figure in it is computed here from the data.
"""

from __future__ import annotations

import re
from typing import Any, Union

import pandas as pd

from plotline.agents.aggregator import ISSUE_FIELD, validate_criteria
from plotline.contract import (
    BHK_VALUES,
    CANONICAL_LOCALITIES,
    Criteria,
    ErrorInfo,
    Notice,
    TraceEvent,
    window_months,
)
from plotline.state import DataInfo, Failure, L1Request
from plotline.trace import TraceLog

_MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_name(m: str) -> str:
    """'2012-05' -> 'May 2012'."""
    return f"{_MONTH_NAMES[int(m[5:7]) - 1]} {m[:4]}"


def inr(x: float) -> str:
    """Rupees as people say them: lakh below a crore, crore above."""
    if x >= 10_000_000:
        return f"₹{x / 10_000_000:.4g} crore"
    return f"₹{x / 100_000:.4g} lakh"


def bhk_list(values) -> str:
    v = sorted(values)
    if len(v) > 1 and v == list(range(v[0], v[-1] + 1)):
        return f"{v[0]}–{v[-1]} BHK"
    return ", ".join(str(b) for b in v) + " BHK"


def coverage_sentence() -> str:
    return f"This data covers 7 Chennai localities: {', '.join(CANONICAL_LOCALITIES)}."


# -- before the scan -------------------------------------------------------------


def inspect(effective: Criteria, info: DataInfo, trace: TraceLog) -> Union[L1Request, Failure, None]:
    """An L1 request for what the Planner can repair, a failure for what it cannot, or None."""
    problem = validate_criteria(effective, info)
    if problem is None:
        trace.step("inspector", "request is within the data")
    elif isinstance(problem, L1Request):
        trace.warning("inspector", f"outside the data: {', '.join(problem.issues)}; asking the planner to repair (L1)",
                      issues=problem.issues)
    return problem


# -- at the end: notices ----------------------------------------------------------


def notices(events: list[TraceEvent], info: DataInfo, effective: Criteria | None,
            criteria_in: Criteria | None, df: pd.DataFrame | None, error: ErrorInfo | None) -> list[Notice]:
    out: list[Notice] = []
    for ev in events:
        if ev.kind == "loop" and ev.loop == "L1":
            out += _repair_notices(ev.data, info)
        elif ev.kind == "warning" and ev.agent == "planner" and ev.msg.startswith("parse audit"):
            fields = ", ".join(_FIELD_WORDS.get(f, f) for f in ev.data.get("fields", []))
            out.append(Notice(kind="not_read", text=f"Your question mentions the {fields}, but it could not be read, "
                                                    "so the result does not use it. Try rephrasing it."))
    if error is not None:
        # the message names the field for the contract (6.5); the user gets the sentence after it
        out.append(Notice(kind="out_of_scope", text=re.sub(r"^invalid \w+: ", "", error.message)))
        return out
    if effective is not None and criteria_in is not None and any(
            e.kind == "loop" and e.loop == "L2" for e in events):
        out.append(_widened_notice(criteria_in, effective))
    if effective is not None and df is not None:
        out += no_sales(effective, df, info)
    return out


_FIELD_WORDS = {"bhk": "BHK", "price_band": "price", "window_end": "year or month", "sqft_range": "size"}


def _repair_notices(data: dict[str, Any], info: DataInfo) -> list[Notice]:
    issues = data["issue"].split("+")
    before, after = data["before"], data["after"]
    if len(issues) > 1:  # one pass repaired several fields: before/after are {field: value}
        return [n for issue in issues
                for n in _repair_notices({"issue": issue, "before": before[ISSUE_FIELD[issue]],
                                          "after": after[ISSUE_FIELD[issue]]}, info)]
    issue = issues[0]
    if issue == "window_out_of_range":
        if before > info.latest_month:
            text = (f"There is no data after {month_name(info.latest_month)} (you asked about "
                    f"{month_name(before)}), so this shows the 12 months to {month_name(after)}.")
        else:
            text = (f"The data starts in {month_name(info.first_month)}, so the earliest 12 months it can show end in "
                    f"{month_name(after)} (you asked about {month_name(before)}).")
        text += (f" You can ask about any 12 months ending between {month_name(info.first_valid_end)} "
                 f"and {month_name(info.latest_month)}.")
    elif issue == "band_inverted":
        text = f"The price range was given high to low; read as {inr(after[0])} to {inr(after[1])}."
    elif issue == "bhk_out_of_range":
        dropped = sorted(set(before) - set(after))
        text = (f"This data has {bhk_list(BHK_VALUES)} homes only, so {bhk_list(dropped)} was left out; "
                f"showing {bhk_list(after)}.")
    elif issue == "locality_unknown":
        changed = [f"'{b}' as {a}" for b, a in zip(before, after) if b != a] or [f"{before} as {after}"]
        text = "Read " + ", ".join(changed) + "."
    else:
        text = f"Repaired {issue}: {before} -> {after}."
    return [Notice(kind="repaired", text=text)]


def _widened_notice(criteria_in: Criteria, effective: Criteria) -> Notice:
    if effective.price_band is None and criteria_in.price_band is not None:
        return Notice(kind="widened", text="Too few sales matched your price range, so the price filter was dropped; "
                                           "the trend covers all prices.")
    if effective.price_band is not None:
        lo, hi = effective.price_band
        return Notice(kind="widened", text=f"Too few sales matched your filters, so the price range was widened "
                                           f"to {inr(lo)} – {inr(hi)}.")
    return Notice(kind="widened", text="Too few sales matched your filters, so the soft filters were widened.")


def no_sales(effective: Criteria, df: pd.DataFrame, info: DataInfo) -> list[Notice]:
    """One notice per requested locality with no sales for the hard filters, saying what it holds."""
    assert effective.window_end is not None
    months = window_months(effective.window_end)
    span = f"the 12 months to {month_name(effective.window_end)}"
    locs = sorted(set(effective.localities)) if effective.localities is not None else list(CANONICAL_LOCALITIES)
    sel = df["sale_date"].astype(str).str[:7].isin(months) & df["locality"].isin(locs)
    if effective.bhk is not None:
        sel &= df["bhk"].isin(effective.bhk)
    have = set(df.loc[sel, "locality"])
    missing = [loc for loc in locs if loc not in have]
    if not missing:
        return []
    what = f"{bhk_list(effective.bhk)} sales" if effective.bhk is not None else "sales"
    reasons = []
    for loc in missing:
        p = info.locality(loc)
        if p is None:
            reasons.append(f"{loc} has no sales in this data")
            continue
        holds = f"{loc} has {bhk_list(p.bhk)} sales from {month_name(p.first_month)} to {month_name(p.last_month)}"
        reasons.append(holds)
    head = (f"No {what} in {span}" + (" for any requested locality." if len(missing) == len(locs)
                                      else f" in {', '.join(missing)}."))
    return [Notice(kind="no_sales", text=head + " In this data, " + "; ".join(reasons) + ".")]
