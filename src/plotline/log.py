"""Logging for the engine (side channel only).

Nothing here touches the ``TrendReport``: no timestamps or durations are ever
written into trace events, so I-DET (byte-identical reports) still holds.
Timestamps come only from the log *formatter* chosen by whoever configures
logging (see ``configure_logging`` and ``tests/conftest.py``).

Two loggers are used:
  plotline.trace         every ``TraceEvent`` as it is created (agents' own messages)
  plotline.orchestrator  run start/end and each agent call's inputs/outputs
"""

from __future__ import annotations

import dataclasses
import functools
import json
import logging
import time
from pathlib import Path
from typing import Any

import pandas as pd

from plotline.state import AgentSet, Analysis, CoverageDecision, Failure, L1Request, PlanResult

trace_log = logging.getLogger("plotline.trace")
orch_log = logging.getLogger("plotline.orchestrator")

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)-21s %(message)s"
_MAX_DEBUG_CHARS = 4000

# which trace agent name each AgentSet function reports as
_AGENT_NAME = {
    "plan": "planner", "repair": "planner", "scan": "scanner", "aggregate": "aggregator",
    "validate": "validator", "analyse": "anomaly", "diagnose": "diagnostic",
}


def configure_logging(path: str | Path | None = "plotline.log", level: int = logging.INFO) -> None:
    """Console + file logging for scripts / the API. Call once at start-up."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if path is not None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    logging.basicConfig(level=level, format=LOG_FORMAT, handlers=handlers, force=True)


_MAX_ITEMS = 5  # DEBUG output shows the first few items of a long list, plus the total


def _dump(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _dump(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, (list, tuple)):
        items = [_dump(x) for x in obj[:_MAX_ITEMS]]
        return items if len(obj) <= _MAX_ITEMS else {"total": len(obj), f"first_{_MAX_ITEMS}": items}
    if isinstance(obj, dict):
        return {k: _dump(v) for k, v in obj.items()}
    return obj


def _js(obj: Any, limit: int | None = None) -> str:
    s = json.dumps(_dump(obj), default=str, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    return s if limit is None or len(s) <= limit else s[:limit] + f"...[{len(s)} chars]"


def summarize(obj: Any) -> str:
    """One-line description of what an agent returned."""
    if isinstance(obj, Failure):
        return f"FAILURE {obj.error.code}: {obj.error.message}"
    if isinstance(obj, L1Request):
        return f"L1 request: fields={obj.fields} issues={obj.issues}"
    if isinstance(obj, PlanResult):
        return (f"plan topology={obj.topology} n_scanners={obj.n_scanners} "
                f"effective={_js(obj.effective)}")
    if isinstance(obj, CoverageDecision):
        widen = _js(obj.widen_to) if obj.widen_to is not None else None
        return (f"coverage_months={obj.coverage_months} coverage_score={obj.coverage_score} "
                f"widen_to={widen}")
    if isinstance(obj, Analysis):
        return f"records={len(obj.records)} flags={len(obj.flags)} summary={_js(obj.summary)}"
    if isinstance(obj, pd.DataFrame):
        return f"rows={len(obj)} cols={list(obj.columns)}"
    if isinstance(obj, list):
        return f"{len(obj)} item(s)"
    return repr(obj)


def logged_agents(agents: AgentSet) -> AgentSet:
    """Wrap every agent function so each call logs its output and duration."""
    wrapped = {}
    for f in dataclasses.fields(agents):
        wrapped[f.name] = _wrap(f.name, getattr(agents, f.name))
    return AgentSet(**wrapped)


def _wrap(fn_name: str, fn):
    agent = _AGENT_NAME.get(fn_name, fn_name)

    @functools.wraps(fn)
    def inner(*args, **kwargs):
        orch_log.info("[%s] %s: start", agent, fn_name)
        t0 = time.perf_counter()
        try:
            out = fn(*args, **kwargs)
        except Exception:
            orch_log.exception("[%s] %s: RAISED after %.1f ms", agent, fn_name,
                               (time.perf_counter() - t0) * 1000)
            raise
        ms = (time.perf_counter() - t0) * 1000
        level = logging.WARNING if isinstance(out, (Failure, L1Request)) else logging.INFO
        orch_log.log(level, "[%s] %s: done in %.1f ms -> %s", agent, fn_name, ms, summarize(out))
        if orch_log.isEnabledFor(logging.DEBUG):
            orch_log.debug("[%s] %s: full output -> %s", agent, fn_name, _full(out))
        return out

    return inner


def _full(out: Any) -> str:
    if isinstance(out, pd.DataFrame):
        return out.head(20).to_json(orient="records")[:_MAX_DEBUG_CHARS]
    if isinstance(out, PlanResult):
        return _js({"effective": out.effective, "criteria_in": out.criteria_in,
                    "topology": out.topology, "n_scanners": out.n_scanners}, _MAX_DEBUG_CHARS)
    if isinstance(out, (CoverageDecision, Analysis, L1Request, Failure)):
        return _js(out, _MAX_DEBUG_CHARS)
    if isinstance(out, list):
        return _js(out, _MAX_DEBUG_CHARS)
    return repr(out)[:_MAX_DEBUG_CHARS]
