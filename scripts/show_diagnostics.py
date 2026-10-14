#!/usr/bin/env python3
"""Show the Diagnostic's explanation for flagged months, on the real snapshot.

    uv run python scripts/show_diagnostics.py                  # live model from .env
    uv run python scripts/show_diagnostics.py --template       # no model: template text
    uv run python scripts/show_diagnostics.py --no-spike       # the unmodified snapshot
    uv run python scripts/show_diagnostics.py --base-url http://localhost:1234/v1

By default a fake +50 % price spike is inserted into 2014-06 of a COPY of the data
(the snapshot file is never touched), so there is a flagged month to explain.
The explanation is UI text only: it never changes a number in the report.
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from plotline.contract import Criteria  # noqa: E402
from plotline.llm_client import LlmClient, LlmConfig  # noqa: E402
from plotline.orchestrator import Engine  # noqa: E402

SPIKE_MONTH = "2014-06"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", action="store_true", help="no model: template text only")
    ap.add_argument("--no-spike", action="store_true", help="do not insert the fake spike")
    ap.add_argument("--base-url")
    ap.add_argument("--window-end", default="2015-02")
    args = ap.parse_args()
    logging.disable(logging.CRITICAL)

    df = pd.read_csv(ROOT / "data" / "chennai_snapshot.csv")
    if not args.no_spike:
        in_month = df["sale_date"].str[:7] == SPIKE_MONTH
        df.loc[in_month, "price"] = df.loc[in_month, "price"] * 1.5
        print(f"Inserted a fake +50% price spike into {SPIKE_MONTH} ({int(in_month.sum())} rows, copy only)")

    if args.template:
        engine = Engine.from_data_dir(ROOT / "data", llm_mode="off")
        print("Mode: template (no model)\n")
    else:
        config = LlmConfig.from_env()
        if config.mode == "off":
            print("ERROR: LLM_MODE is off; use live/replay in .env or pass --template", file=sys.stderr)
            return 2
        if args.base_url:
            config = replace(config, base_url=args.base_url)
        engine = Engine.from_data_dir(ROOT / "data", llm_client=LlmClient(config))
        print(f"Mode: {config.mode}  model: {config.model}  endpoint: {config.base_url}\n")

    report = engine.run(Criteria(window_end=args.window_end), df)
    if report.status != "ok":
        print(f"ERROR {report.error.code}: {report.error.message}", file=sys.stderr)
        return 1
    if not report.anomaly_flags:
        print("No flagged months.")
        return 0
    diags: dict[str, list] = {}
    for d in report.diagnostics:
        diags.setdefault(d.month, []).append(d)
    for flag in report.anomaly_flags:
        d = diags[flag.month].pop(0)
        print(f"{flag.month}  {flag.kind:<10} value={flag.value:+.4f} (threshold {flag.threshold})")
        print(f"   flag reason : {flag.reason}")
        print(f"   explanation : {d.text}   [{d.source}]\n")
    for e in report.trace:
        if e.agent == "diagnostic":
            print(f"trace [{e.kind}] {e.msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
