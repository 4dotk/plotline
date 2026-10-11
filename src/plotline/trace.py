"""Trace logger (CONTRACT.md 7.4).

One ``TraceLog`` per run. Every event is a validated ``TraceEvent`` with ``i``
counting from 0 with no gaps. Loop firings use the exact message templates and
data keys of 7.4, built from the section 3 constants so the templates cannot
drift. ``loop_counters()`` is derived from the events, so it always equals the
number of ``kind = "loop"`` events (I-CAP).

Agents write their own events through this object. The orchestrator never
invents loop events; it only checks the counters.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from plotline.contract import (
    COVERAGE_MIN_MONTHS,
    L1_CAP,
    L2_CAP,
    L2_WIDEN,
    WINDOW_MONTHS,
    LoopCounters,
    TraceEvent,
)

_log = logging.getLogger("plotline.trace")
_LEVEL = {"warning": logging.WARNING, "error": logging.ERROR}  # step/decision/loop -> INFO


def _fmt(value: Any) -> str:
    """Compact, deterministic text for a value inside a message."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def l2_action_text(factor: float | str) -> str:
    """Human text for an L2 step, derived from the ``L2_WIDEN`` factor."""
    if factor == "drop":
        return "drop soft filters"
    return f"widen soft ranges by {round(float(factor) * 100)}%"


class TraceLog:
    def __init__(self) -> None:
        self._events: list[TraceEvent] = []

    # -- generic events -------------------------------------------------------

    def _add(self, agent: str, kind: str, loop: str | None, msg: str, data: dict[str, Any]) -> TraceEvent:
        ev = TraceEvent(
            i=len(self._events), agent=agent, kind=kind, loop=loop, msg=msg, data=dict(data)
        )
        self._events.append(ev)
        # side channel only: never part of the report (I-DET)
        tag = f"{kind}:{loop}" if loop else kind
        _log.log(_LEVEL.get(kind, logging.INFO), "#%d [%s] %s | %s | data=%s", ev.i, agent, tag, msg, _fmt(ev.data))
        return ev

    def step(self, agent: str, msg: str, **data: Any) -> TraceEvent:
        return self._add(agent, "step", None, msg, data)

    def decision(self, agent: str, msg: str, **data: Any) -> TraceEvent:
        return self._add(agent, "decision", None, msg, data)

    def warning(self, agent: str, msg: str, **data: Any) -> TraceEvent:
        return self._add(agent, "warning", None, msg, data)

    def error(self, agent: str, msg: str, **data: Any) -> TraceEvent:
        return self._add(agent, "error", None, msg, data)

    # -- loop firings (exact templates, 7.4) ---------------------------------

    def l1_fired(self, issue: str, before: Any, after: Any, repair_no: int) -> TraceEvent:
        """Written by agent ``planner`` at the moment of repair."""
        msg = f"L1 fired: {issue}; {_fmt(before)} -> {_fmt(after)}; repair {repair_no} of {L1_CAP}"
        data = {
            "issue": issue,
            "before": before,
            "after": after,
            "repair_no": repair_no,
            "cap": L1_CAP,
        }
        return self._add("planner", "loop", "L1", msg, data)

    def l2_fired(
        self,
        coverage_months: int,
        attempt: int,
        effective_price_band: list[float | int] | None,
        decided_by: str = "rule",
    ) -> TraceEvent:
        """Written by agent ``validator``. ``factor`` mirrors ``L2_WIDEN``."""
        if not 1 <= attempt <= L2_CAP:
            raise ValueError(f"L2 attempt must be in 1..{L2_CAP}, got {attempt}")
        factor = L2_WIDEN[attempt - 1]
        action = l2_action_text(factor)
        msg = (
            f"L2 fired: coverage {coverage_months}/{WINDOW_MONTHS} below "
            f"{COVERAGE_MIN_MONTHS}/{WINDOW_MONTHS}; {action}; attempt {attempt} of {L2_CAP}"
        )
        data = {
            "coverage_months": coverage_months,
            "need_months": COVERAGE_MIN_MONTHS,
            "action": action,
            "factor": factor,
            "attempt": attempt,
            "cap": L2_CAP,
            "effective_price_band": effective_price_band,
            "decided_by": decided_by,
        }
        return self._add("validator", "loop", "L2", msg, data)

    # -- non-firing L2 outcomes (never counted as loop firings) ---------------

    def l2_skipped(self) -> TraceEvent:
        return self.decision("validator", "L2 skipped: nothing to widen")

    def l2_disabled(self) -> TraceEvent:
        return self.warning("validator", "L2 disabled")

    def l2_stopped_by_model(self, coverage_months: int) -> TraceEvent:
        msg = (
            f"L2 stopped by model: coverage {coverage_months}/{WINDOW_MONTHS}, "
            f"need {COVERAGE_MIN_MONTHS}/{WINDOW_MONTHS}"
        )
        return self.decision("validator", msg)

    # -- read side ------------------------------------------------------------

    @property
    def events(self) -> list[TraceEvent]:
        return list(self._events)

    def loop_counters(self) -> LoopCounters:
        l1 = sum(1 for e in self._events if e.kind == "loop" and e.loop == "L1")
        l2 = sum(1 for e in self._events if e.kind == "loop" and e.loop == "L2")
        return LoopCounters(L1_repairs=l1, L2_attempts=l2)
