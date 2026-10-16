#!/usr/bin/env python3
"""20 smoke queries through the AI-mode Planner: do they all parse to valid filters?

    uv run python scripts/smoke_20_queries.py                 # live model from .env (LLM_BASE_URL)
    uv run python scripts/smoke_20_queries.py --base-url http://localhost:1234/v1
    uv run python scripts/smoke_20_queries.py --rules-only    # no model: the rule-based parser alone
    uv run python scripts/smoke_20_queries.py --out results/smoke_20_queries.jsonl

Each sentence goes through the real code path: llm_client -> Planner (fallback to the
rule-based parser when the model's output stays unusable) -> Scanner -> Aggregator
(the same validation as for manual filters; L1 repairs what it can).

A query PASSES only when it is read RIGHT: the filters equal the expected ones in
the query set, or the run fails with the expected error code. Being valid is not
enough (until 10-16 it was, so a wrong reading still passed). Each query is also
classed as:
    right      as expected
    flagged    wrong, but the planner's parse audit warned about it in the trace
    SILENT     wrong, status ok, no warning: the worst case (the user gets an answer
               to a question they did not ask)
    error      an error report that was not expected
Exit code 0 only if every query passes.

    uv run python scripts/smoke_20_queries.py --queries tests.nl_eval_queries   # the larger set
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # so `tests.smoke_queries` imports when run as a script

from plotline.llm_client import LlmClient, LlmConfig  # noqa: E402
from plotline.orchestrator import Engine  # noqa: E402
from tests.smoke_queries import HARD, SOFT  # noqa: E402
from tests.support import FakeChat, llm_config  # noqa: E402


def source_of(report) -> str:
    msgs = [e.msg for e in report.trace if e.agent == "planner"]
    if any(m.startswith("fallback: rule-based parser") for m in msgs):
        return "rules(fallback)"
    if any(m == "sentence parsed by the model" for m in msgs):
        return "model"
    return "rules"


RANGES = ("price_band", "sqft_range")  # [hi, lo] and [lo, hi] are the same request; L1 swaps the first


def ordered(filters: dict) -> dict:
    return {k: (sorted(v) if k in RANGES and v is not None else v) for k, v in filters.items()}


def got_filters(report) -> dict:
    eff, cin = report.effective_criteria, report.criteria_in
    return ordered({**{k: getattr(eff, k) for k in HARD}, **{k: getattr(cin, k) for k in SOFT}})


def judge(report, expected) -> tuple[bool, bool, str, int, dict]:
    """(passed, matched, class, L1 repairs, diff) of one report against its expected reading."""
    audited = any(e.msg.startswith("parse audit") for e in report.trace)

    if report.status != "ok":
        err = f"{report.error.code}: {report.error.message}"
        match = isinstance(expected, str) and report.error.code == expected
        valid, l1, diff = match, report.metadata.loop_counters.L1_repairs, ({} if match else {"error": err})
        klass = "right" if match else "error"
    elif isinstance(expected, str):  # an error was expected, an answer came back
        valid, match, l1 = False, False, report.metadata.loop_counters.L1_repairs
        diff = {"status": {"got": "ok", "expected": expected}, **{"effective": report.effective_criteria.model_dump(mode="json")}}
        klass = "flagged" if audited else "SILENT"
    else:
        got = got_filters(report)
        diff = {k: {"got": got[k], "expected": v} for k, v in ordered(expected).items() if got[k] != v}
        match, l1 = not diff, report.metadata.loop_counters.L1_repairs
        valid = match and not report.effective_criteria.domain_violations()
        klass = "right" if match else ("flagged" if audited else "SILENT")
    return valid, match, klass, l1, diff


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rules-only", action="store_true", help="use only the rule-based parser (no model)")
    ap.add_argument("--base-url", help="override LLM_BASE_URL, e.g. http://localhost:1234/v1")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", help="write one JSON line per query to this file")
    ap.add_argument("-v", "--verbose", action="store_true", help="show the planner trace of every query")
    ap.add_argument("--queries", default="tests.smoke_queries", help="module with QUERIES (default: the 20)")
    args = ap.parse_args()
    logging.disable(logging.CRITICAL)
    QUERIES = importlib.import_module(args.queries).QUERIES

    df = pd.read_csv(ROOT / "data" / "chennai_snapshot.csv")

    if args.rules_only:
        # the real AI-mode path with a model that never answers usefully: the planner falls back to
        # the rule-based parser exactly as it does live, and its parse audit runs
        engine = Engine.from_data_dir(ROOT / "data", llm_client=LlmClient(llm_config("live"), chat=FakeChat("not json")))
        print("Mode: rule-based parser only (model stubbed to fail)\n")
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
    classes: dict[str, int] = {}
    print(f"{'#':>2}  {'source':<15} {'L1':>2}  {'pass':<5} {'class':<8} query")
    for n, (sentence, expected, _min_l1) in enumerate(QUERIES, 1):
        report = engine.run(sentence, df, args.seed)
        source = source_of(report)
        valid, match, klass, l1, diff = judge(report, expected)
        n_pass += valid
        n_match += match
        classes[klass] = classes.get(klass, 0) + 1
        print(f"{n:>2}  {source:<15} {l1:>2}  {'PASS' if valid else 'FAIL':<5} {klass:<8} {sentence}")
        for k, d in diff.items():
            print(f"        - {k}: {d}")
        if report is not None and (args.verbose or not valid):
            for e in report.trace:
                if e.agent in ("planner", "aggregator") and (args.verbose or e.kind in ("warning", "error")):
                    print(f"        [{e.agent}] {e.kind}: {e.msg[:200]}")
        results.append({
            "n": n, "query": sentence, "source": source, "pass": valid, "match": match, "class": klass,
            "l1_repairs": l1, "status": report.status,
            "criteria_in": report.criteria_in.model_dump(mode="json") if report.criteria_in else None,
            "effective": report.effective_criteria.model_dump(mode="json") if report.effective_criteria else None,
            "diff": diff,
            "planner_warnings": [e.msg for e in report.trace if e.agent == "planner" and e.kind == "warning"],
            "notices": [n.model_dump(mode="json") for n in report.notices],  # what the user is told (1.2.0)
        })

    by_source: dict[str, int] = {}
    for r in results:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    print(f"\npassed (read right): {n_pass}/{len(QUERIES)}   classes: {classes}   sources: {by_source}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n")
        print(f"wrote {args.out}")
    return 0 if n_pass == len(QUERIES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
