#!/usr/bin/env python3
"""20 smoke queries through the AI-mode Planner: do they all parse to valid filters?

    uv run python scripts/smoke_20_queries.py                 # live model from .env (LLM_BASE_URL)
    uv run python scripts/smoke_20_queries.py --base-url http://localhost:1234/v1
    uv run python scripts/smoke_20_queries.py --rules-only    # no model: the rule-based parser alone
    uv run python scripts/smoke_20_queries.py --out results/smoke_20_queries.jsonl

Each sentence goes through the real code path: llm_client -> Planner (fallback to the
rule-based parser when the model's output stays unusable) -> Scanner -> Aggregator
(the same validation as for manual filters; L1 repairs what it can).

A query PASSES when the run is ``ok`` and the criteria it computed are valid.
MATCH (informational) says whether the parsed filters equal the expected ones in
tests/smoke_queries.py. Exit code 0 only if all 20 pass.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # so `tests.smoke_queries` imports when run as a script

from plotline.agents import nl_rules  # noqa: E402
from plotline.contract import Criteria  # noqa: E402
from plotline.llm_client import LlmClient, LlmConfig  # noqa: E402
from plotline.orchestrator import Engine  # noqa: E402
from plotline.state import DataInfo  # noqa: E402
from tests.smoke_queries import HARD, QUERIES, SOFT  # noqa: E402


def source_of(report) -> str:
    msgs = [e.msg for e in report.trace if e.agent == "planner"]
    if any(m.startswith("fallback: rule-based parser") for m in msgs):
        return "rules(fallback)"
    if any(m == "sentence parsed by the model" for m in msgs):
        return "model"
    return "rules"


def got_filters(report) -> dict:
    eff, cin = report.effective_criteria, report.criteria_in
    return {**{k: getattr(eff, k) for k in HARD}, **{k: getattr(cin, k) for k in SOFT}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rules-only", action="store_true", help="use only the rule-based parser (no model)")
    ap.add_argument("--base-url", help="override LLM_BASE_URL, e.g. http://localhost:1234/v1")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", help="write one JSON line per query to this file")
    ap.add_argument("-v", "--verbose", action="store_true", help="show the planner trace of every query")
    args = ap.parse_args()
    logging.disable(logging.CRITICAL)

    df = pd.read_csv(ROOT / "data" / "chennai_snapshot.csv")
    months = df["sale_date"].str[:7]
    info = DataInfo(first_month=str(months.min()), latest_month=str(months.max()))

    if args.rules_only:
        engine = Engine.from_data_dir(ROOT / "data", llm_mode="off")
        print("Mode: rule-based parser only (no model)\n")
    else:
        config = LlmConfig.from_env()
        if config.mode == "off":
            print("ERROR: LLM_MODE is off; set it to live (or replay) in .env, or use --rules-only", file=sys.stderr)
            return 2
        if args.base_url:
            config = replace(config, base_url=args.base_url)
        engine = Engine.from_data_dir(ROOT / "data", llm_client=LlmClient(config))
        print(f"Mode: {config.mode}  model: {config.model}  endpoint: {config.base_url}\n")

    results, n_pass, n_match = [], 0, 0
    print(f"{'#':>2}  {'source':<15} {'L1':>2}  {'pass':<5} {'match':<5}  query")
    for n, (sentence, expected, _min_l1) in enumerate(QUERIES, 1):
        if args.rules_only:
            parsed = nl_rules.parse(sentence, info)
            report = engine.run(parsed, df, args.seed) if parsed is not None else None
            source = "rules"
        else:
            report = engine.run(sentence, df, args.seed)
            source = source_of(report)

        if report is None or report.status != "ok":
            err = (report.error.code + ": " + report.error.message) if report else "unparseable"
            valid, match, l1, diff = False, False, 0, {"error": err}
        else:
            valid = not report.effective_criteria.domain_violations()
            got = got_filters(report)
            diff = {k: {"got": got[k], "expected": v} for k, v in expected.items() if got[k] != v}
            match, l1 = not diff, report.metadata.loop_counters.L1_repairs
        n_pass += valid
        n_match += match
        print(f"{n:>2}  {source:<15} {l1:>2}  {'PASS' if valid else 'FAIL':<5} {'yes' if match else 'NO':<5}  {sentence}")
        for k, d in diff.items():
            print(f"        - {k}: {d}")
        if report is not None and (args.verbose or not valid):
            for e in report.trace:
                if e.agent in ("planner", "aggregator") and (args.verbose or e.kind in ("warning", "error")):
                    print(f"        [{e.agent}] {e.kind}: {e.msg[:200]}")
        results.append({
            "n": n, "query": sentence, "source": source, "pass": valid, "match": match, "l1_repairs": l1,
            "status": report.status if report else "error",
            "criteria_in": report.criteria_in.model_dump(mode="json") if report and report.criteria_in else None,
            "effective": report.effective_criteria.model_dump(mode="json") if report and report.effective_criteria else None,
            "diff": diff,
            "planner_warnings": [e.msg for e in report.trace if e.agent == "planner" and e.kind == "warning"] if report else [],
        })

    by_source: dict[str, int] = {}
    for r in results:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    print(f"\nvalid: {n_pass}/{len(QUERIES)}   matched expected: {n_match}/{len(QUERIES)}   sources: {by_source}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n")
        print(f"wrote {args.out}")
    return 0 if n_pass == len(QUERIES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
