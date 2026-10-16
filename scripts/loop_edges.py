#!/usr/bin/env python3
"""Which control-flow edges (loops, repairs, refusals, notices) each test layer exercises.

    uv run python scripts/loop_edges.py [--bases 350]

Counted from the trace and report of every run the layer makes:
    mt         every source and follow-up run of the Mode A MR sweep (MR1-MR11; MR9 via the rule parser)
    freetext   every sentence of tests/smoke_queries, tests/nl_eval_queries and
               tests/nl_l1_scenarios through the AI-mode path, model stubbed (rule parser)
    model      the live-model runs already recorded in results/nl_eval/*model*.jsonl
               (only what the result files hold: L1 repairs, status, notices)

Writes results/adequacy/loop_edges.md and loop_edges.json. An edge with 0 in every
layer is never exercised by any of these tests.
"""
from __future__ import annotations

import argparse
import importlib
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from plotline.contract import RunOptions
from plotline.llm_client import LlmClient
from plotline.orchestrator import Engine
from tests.mt.generator import SNAPSHOT, load_bases
from tests.mt.harness import run_mr
from tests.mt.mrs import MRS
from tests.mt.mrs.mr09_paraphrase import with_phrasings
from tests.mt.run import mode_a_engine, rules_engine
from tests.support import FakeChat, llm_config

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "adequacy"
EDGES = [
    "runs", "status ok", "error report",
    "L1 fired (any)", "L1 window_out_of_range", "L1 band_inverted", "L1 bhk_out_of_range", "L1 locality_unknown",
    "L1 several issues in one pass", "L1 cannot repair -> error",
    "L2 attempt 1 (20%)", "L2 attempt 2 (50%)", "L2 attempt 3 (drop)", "L2 cap reached",
    "L2 nothing to widen", "L2 stopped by model",
    "topology parallel", "topology consolidated",
    "notice repaired", "notice out_of_scope", "notice no_sales", "notice widened", "notice not_read",
]


def count(report, c: Counter) -> None:
    c["runs"] += 1
    c["status ok" if report.status == "ok" else "error report"] += 1
    if report.metadata.topology:
        c[f"topology {report.metadata.topology}"] += 1
    l1 = [e for e in report.trace if e.kind == "loop" and e.loop == "L1"]
    if l1:
        c["L1 fired (any)"] += 1
    for e in l1:
        issues = e.data["issue"].split("+")
        if len(issues) > 1:
            c["L1 several issues in one pass"] += 1
        for i in issues:
            c[f"L1 {i}"] += 1
    if report.error and report.error.code == "E_INVALID_CRITERIA":
        c["L1 cannot repair -> error"] += 1
    for e in report.trace:
        if e.kind == "loop" and e.loop == "L2":
            c[{1: "L2 attempt 1 (20%)", 2: "L2 attempt 2 (50%)", 3: "L2 attempt 3 (drop)"}[e.data["attempt"]]] += 1
        elif e.agent == "validator" and e.kind == "decision":
            if e.msg.startswith("L2 cap reached"):
                c["L2 cap reached"] += 1
            elif e.msg.startswith("L2 skipped: nothing to widen"):
                c["L2 nothing to widen"] += 1
            elif e.msg.startswith("L2 stopped by model"):
                c["L2 stopped by model"] += 1
    for n in report.notices:
        c[f"notice {n.kind}"] += 1


def mt_layer(bases: int) -> Counter:
    df = pd.read_csv(SNAPSHOT)
    eng = mode_a_engine()
    c: Counter = Counter()

    def counting(q, d, s, o):
        r = eng.run(q, d, s, o)
        count(r, c)
        return r

    rules = rules_engine()

    def counting_rules(q, d, s, o):
        r = rules.run(q, d, s, o)
        count(r, c)
        return r

    bs = with_phrasings(load_bases(ROOT / "results" / "bases_and_params.json")[:bases], df)
    for name in sorted(MRS):  # MR9 through the rule parser (model stubbed), as in tests/mt/run.py
        run_mr(MRS[name], bs, df, counting_rules if name == "MR9" else counting, (0,), check_invariants=False)
    return c


def freetext_layer() -> Counter:
    df = pd.read_csv(SNAPSHOT)
    eng = Engine.from_data_dir(ROOT / "data", llm_client=LlmClient(llm_config("live"), chat=FakeChat("not json")))
    c: Counter = Counter()
    for mod in ("tests.smoke_queries", "tests.nl_eval_queries", "tests.nl_l1_scenarios"):
        for sentence, _, _ in importlib.import_module(mod).QUERIES:
            count(eng.run(sentence, df, 0, RunOptions()), c)
    return c


def model_layer() -> Counter:
    c: Counter = Counter()
    for f in sorted((ROOT / "results" / "nl_eval").glob("*model*.jsonl")):
        for line in f.read_text().splitlines():
            r = json.loads(line)
            c["runs"] += 1
            c["status ok" if r["status"] == "ok" else "error report"] += 1
            if r.get("l1_repairs"):
                c["L1 fired (any)"] += 1
            for n in r.get("notices", []):
                c[f"notice {n['kind']}"] += 1
    return c


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bases", type=int, default=350)
    args = ap.parse_args()
    import logging
    logging.disable(logging.CRITICAL)
    layers = {"mt": mt_layer(args.bases), "freetext": freetext_layer(), "model": model_layer()}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "loop_edges.json").write_text(json.dumps({k: dict(v) for k, v in layers.items()}, indent=1) + "\n")
    names = list(layers)
    lines = [f"# Control-flow edges exercised by each test layer (MT: {args.bases} bases, Mode A)", "",
             "Counts of runs in which each edge occurs, from the trace and the report. "
             "Generated by `scripts/loop_edges.py`. *model* holds only what the live-model result files record "
             "(no L2 detail); a blank there means not recorded, not zero.", "",
             "| Edge | " + " | ".join(names) + " | exercised by |", "|---|" + "---|" * (len(names) + 1)]
    for e in EDGES:
        vals = [layers[n].get(e, 0) for n in names]
        by = ", ".join(n for n, v in zip(names, vals) if v) or "**none**"
        cells = [str(v) if (v or n != "model" or e in ("runs", "status ok", "error report", "L1 fired (any)")
                            or e.startswith("notice")) else "" for n, v in zip(names, vals)]
        lines.append(f"| {e} | " + " | ".join(cells) + f" | {by} |")
    (OUT / "loop_edges.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
