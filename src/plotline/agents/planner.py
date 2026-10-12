"""Agent A: Query Planner (contracts/Planner.md, contracts/_common.md).

Decision-maker. Turns the request into ``Criteria``, picks the scanner topology,
and repairs criteria the aggregator sends back (loop L1). The model is used only
in AI mode (a sentence in), through ``llm_client``; when its output stays
malformed the rule-based parser (``nl_rules``) takes over.
"""

from __future__ import annotations

import difflib
from typing import Any, Union

from plotline.agents import nl_rules
from plotline.contract import (
    BHK_VALUES,
    CANONICAL_LOCALITIES,
    CANONICAL_SALE_CONDS,
    TOPOLOGY_PARALLEL_MIN_LOCALITIES,
    Criteria,
    ErrorInfo,
    LlmMode,
    RunOptions,
)
from plotline.llm_client import LlmSession, load_prompt
from plotline.state import DataInfo, Failure, L1Request, PlanResult
from plotline.trace import TraceLog

LOCALITY_MATCH_CUTOFF = 0.8  # difflib cutoff fixed by the L1 repair table (_common.md)

_ISSUE_FIELD = {
    "band_inverted": "price_band",
    "locality_unknown": "localities",
    "window_out_of_range": "window_end",
    "bhk_out_of_range": "bhk",
    "sale_cond_unknown": "sale_cond",
}


def _invalid(field: str, why: str) -> Failure:
    return Failure(ErrorInfo(code="E_INVALID_CRITERIA", message=f"invalid {field}: {why}"))


# -- plan -----------------------------------------------------------------------


def plan(
    query: Union[Criteria, str], info: DataInfo, options: RunOptions, seed: int,
    llm_mode: LlmMode, trace: TraceLog, llm: LlmSession | None = None,
) -> Union[PlanResult, Failure]:
    if isinstance(query, str):
        parsed = _parse_sentence(query, info, llm_mode, trace, llm)
        if isinstance(parsed, Failure):
            return parsed
        criteria_in = parsed
    else:
        criteria_in = query
    effective = criteria_in.model_copy(deep=True)  # I-PURE: never edit what we were given
    if effective.window_end is None:
        effective.window_end = info.latest_month  # D2: default = latest month
    return with_topology(effective, criteria_in, options, trace)


def with_topology(effective: Criteria, criteria_in: Criteria, options: RunOptions, trace: TraceLog) -> PlanResult:
    n_loc = len(set(effective.localities)) if effective.localities is not None else len(CANONICAL_LOCALITIES)
    if options.force_topology is not None:
        topology = options.force_topology
        why = "forced"
    elif effective.localities is None or n_loc >= TOPOLOGY_PARALLEL_MIN_LOCALITIES:
        topology, why = "parallel", f"{n_loc} localities >= {TOPOLOGY_PARALLEL_MIN_LOCALITIES}"
    else:
        topology, why = "consolidated", f"{n_loc} localities < {TOPOLOGY_PARALLEL_MIN_LOCALITIES}"
    n_scanners = max(n_loc, 1) if topology == "parallel" else 1
    trace.decision("planner", f"topology={topology} ({why})")
    return PlanResult(effective=effective, topology=topology, n_scanners=n_scanners, criteria_in=criteria_in)


def _parse_sentence(
    sentence: str, info: DataInfo, llm_mode: LlmMode, trace: TraceLog, llm: LlmSession | None,
) -> Union[Criteria, Failure]:
    if llm_mode == "off" or llm is None:
        return Failure(ErrorInfo(code="E_LLM_OFF", message="AI mode requested with LLM_MODE=off"))
    system = load_prompt(
        "planner",
        localities=", ".join(CANONICAL_LOCALITIES),
        sale_conds=", ".join(CANONICAL_SALE_CONDS),
        latest_month=info.latest_month,
    )
    out = llm.call("planner", system, sentence, Criteria)
    if out.replay_miss:
        return Failure(ErrorInfo(code="E_REPLAY_MISS", message="planner prompt is not in the replay cache"))
    for failure in out.failures:
        trace.warning("planner", failure)
    if out.value is not None:
        assert isinstance(out.value, Criteria)
        trace.step("planner", "sentence parsed by the model")
        return out.value
    trace.warning("planner", "fallback: rule-based parser (model output unusable)")
    parsed = nl_rules.parse(sentence, info)
    if parsed is None:
        return Failure(ErrorInfo(code="E_NL_UNPARSEABLE",
                                 message="neither the model nor the rule parser understood the sentence"))
    trace.step("planner", "sentence parsed by the rule-based parser")
    return parsed


# -- repair (loop L1) -------------------------------------------------------------


def repair(
    plan_: PlanResult, request: L1Request, info: DataInfo, options: RunOptions,
    l1_repairs: int, trace: TraceLog,
) -> Union[PlanResult, Failure]:
    """Apply every repair in one pass (one L1 firing). Any issue that cannot be
    repaired fails the whole request; nothing is half-repaired."""
    eff = plan_.effective
    changes: dict[str, tuple[Any, Any]] = {}
    for issue in request.issues:
        field = _ISSUE_FIELD.get(issue, "criteria")
        fixed = _repair_one(issue, eff, info)
        if isinstance(fixed, Failure):
            return fixed
        changes[field] = (getattr(eff, field), fixed)

    after = eff.model_copy(deep=True, update={f: new for f, (_, new) in changes.items()})
    issue = "+".join(request.issues)
    if len(changes) == 1:
        (before_v, after_v), = changes.values()
    else:
        before_v = {f: old for f, (old, _) in changes.items()}
        after_v = {f: new for f, (_, new) in changes.items()}
    trace.l1_fired(issue, before_v, after_v, l1_repairs + 1)
    return with_topology(after, plan_.criteria_in, options, trace)


def _repair_one(issue: str, eff: Criteria, info: DataInfo) -> Any:
    if issue == "band_inverted":
        lo, hi = eff.price_band  # type: ignore[misc]
        return [hi, lo]
    if issue == "locality_unknown":
        fixed = []
        for name in eff.localities or []:
            if name in CANONICAL_LOCALITIES:
                fixed.append(name)
                continue
            # Case and edge spaces are not spelling: compare folded, return the canonical name.
            folded = {c.lower(): c for c in CANONICAL_LOCALITIES}
            match = difflib.get_close_matches(name.strip().lower(), list(folded), n=1, cutoff=LOCALITY_MATCH_CUTOFF)
            if not match:
                return _invalid("localities", f"no canonical locality close to {name!r}")
            if folded[match[0]] not in fixed:  # two spellings of one place collapse to one entry
                fixed.append(folded[match[0]])
        return fixed
    if issue == "window_out_of_range":
        assert eff.window_end is not None
        return min(max(eff.window_end, info.first_valid_end), info.latest_month)
    if issue == "bhk_out_of_range":
        kept = [b for b in eff.bhk or [] if b in BHK_VALUES]
        return kept if kept else _invalid("bhk", f"no value of {eff.bhk} is in {list(BHK_VALUES)}")
    if issue == "sale_cond_unknown":
        return _invalid("sale_cond", f"{eff.sale_cond} has a value outside {list(CANONICAL_SALE_CONDS)}")
    return _invalid(_ISSUE_FIELD.get(issue, "criteria"), f"no repair for issue {issue!r}")
