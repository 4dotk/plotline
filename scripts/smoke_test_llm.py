#!/usr/bin/env python3
"""One-sentence smoke test of the AI-mode Planner against the configured model.

Run from repository root (needs LLM_MODE=live or replay in .env):
    uv run python scripts/smoke_test_llm.py
    uv run python scripts/smoke_test_llm.py "Show Adyar 1 BHK houses last year"

Goes through the real code path: llm_client -> Planner (with its rule-based
fallback) -> Scanner on the frozen snapshot. It prints the trace, the criteria
and the matching row count. It does not compute trends (C-G are still stubs).
With LLM_CACHE_WRITE=1 a live run records its answers for replay.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from plotline.agents import planner, scanner
from plotline.contract import RunOptions
from plotline.llm_client import LlmClient, LlmConfig
from plotline.state import DataInfo, Failure
from plotline.trace import TraceLog

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "chennai_snapshot.csv"


def main() -> int:
    config = LlmConfig.from_env()
    if config.mode == "off":
        print("ERROR: set LLM_MODE=live (or replay) in .env", file=sys.stderr)
        return 2
    query = " ".join(sys.argv[1:]).strip() or "Show houses in Adyar up to May 2012."
    seed = 0

    df = pd.read_csv(SNAPSHOT)
    months = df["sale_date"].str[:7]
    info = DataInfo(first_month=str(months.min()), latest_month=str(months.max()))
    trace = TraceLog()
    session = LlmClient(config).session(seed)

    print(f"Mode: {config.mode}  model tag: {config.model_tag}  endpoint: {config.base_url or '-'}")
    print(f"Query: {query}\n")
    plan = planner.plan(query, info, RunOptions(), seed, config.mode, trace, session)
    rows = None if isinstance(plan, Failure) else scanner.scan(plan, df, trace)

    print("TRACE:")
    for ev in trace.events:
        print(f"  #{ev.i} [{ev.agent}] {ev.kind}: {ev.msg}")
    if isinstance(plan, Failure):
        print(f"\nFAILED: {plan.error.code}: {plan.error.message}")
        return 1
    print("\nCRITERIA (effective):")
    print(plan.effective.model_dump_json(indent=2))
    print(f"\nTopology: {plan.topology}, {plan.n_scanners} scanner(s)")
    print(f"Matching rows in the 12-month window: {len(rows)} of {len(df)}")
    print("Note: invalid criteria are repaired by L1 only inside the full engine run.")
    print(f"metadata.llm: {session.info.model_dump_json() if session.info else None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
