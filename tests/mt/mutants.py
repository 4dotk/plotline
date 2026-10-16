"""Mutant testing: plant known bugs in the Aggregator and Validator and see which checks catch them.

    uv run python -m tests.mt.mutants                    # 60 bases, every mutant
    uv run python -m tests.mt.mutants --bases 30 --mutant M1

Each mutant replaces one module-level function with ``unittest.mock.patch``
for the length of its run; the source files are never edited. Per mutant
(and a baseline with no mutant) every MR except MR9 runs on the same bases in
Mode A, with the oracle check and I-DET on. ``changed`` counts the bases whose
source report differs from the baseline: a mutant with ``changed = 0`` is
equivalent on these bases (nothing can catch it).

``unit`` runs ``tests/unit`` in-process under the same patch and counts the
failing tests (the golden L2 example A3 lives there, in ``test_orchestrator.py``).

Writes ``<out>/detection_table.md`` and ``<out>/detection.json``.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from unittest import mock

import numpy as np
import pandas as pd
import pytest

from plotline.contract import ALL_REGION, MIN_BUCKET_N, RunOptions, TrendRecord
from plotline.agents import aggregator, validator
from tests.mt.generator import ROOT, SNAPSHOT, load_bases
from tests.mt.harness import SeedRegistry, report_to_json, run_mr, write_json
from tests.mt.mrs import MRS
from tests.mt.run import mode_a_engine

OUT = ROOT / "results" / "mutants"
MR_NAMES = [n for n in sorted(MRS, key=lambda s: (int(s[2:].rstrip("ab")), s)) if n != "MR9"]


# --- the mutants (each a copy of the original with one change) ---------------

def m1_record(month, region, count, price, ppsf):
    n = len(price)
    return TrendRecord(
        month=month, region_key=region, listing_count=count, n_in_bucket=n,
        median_price=aggregator._median(price), median_price_per_sqft=aggregator._median(ppsf),
        low_sample=n <= MIN_BUCKET_N, pct_change_price_per_sqft=None,  # was: n < MIN_BUCKET_N
    )


def m2_record(month, region, count, price, ppsf):
    n = len(price)
    return TrendRecord(
        month=month, region_key=region, listing_count=count, n_in_bucket=n,
        median_price=aggregator._median(price),
        median_price_per_sqft=float(np.mean(ppsf)) if n else None,  # was: the median
        low_sample=n < MIN_BUCKET_N, pct_change_price_per_sqft=None,
    )


def m3_median(values):
    v = values[1:] if len(values) > 1 else values  # was: all values; now depends on row order
    return float(np.median(np.sort(v))) if len(v) else None


def m4_coverage_months(records):
    return sum(1 for r in records if r.region_key == ALL_REGION and r.n_in_bucket > MIN_BUCKET_N)  # was: >=


def m5_widen_range(rng, factor):
    lo, hi = rng
    return [lo, hi + factor * (hi - lo)]  # was: [max(lo - factor * width, 0), hi + factor * width]


@dataclass(frozen=True)
class Mutant:
    id: str
    target: str
    change: str
    patch: Callable[[], object]


MUTANTS = [
    Mutant("M1", "aggregator._record", "`low_sample = n <= MIN_BUCKET_N` (off by one)",
           lambda: mock.patch.object(aggregator, "_record", m1_record)),
    Mutant("M2", "aggregator._record", "mean instead of median for `median_price_per_sqft`",
           lambda: mock.patch.object(aggregator, "_record", m2_record)),
    Mutant("M3", "aggregator._median", "drops the first value in row order before the median",
           lambda: mock.patch.object(aggregator, "_median", m3_median)),
    Mutant("M4", "validator.coverage_months", "`n_in_bucket > MIN_BUCKET_N` instead of `>=` (L2 fires too often)",
           lambda: mock.patch.object(validator, "coverage_months", m4_coverage_months)),
    Mutant("M5", "validator._widen_range", "L2 widens only the upper end of a range",
           lambda: mock.patch.object(validator, "_widen_range", m5_widen_range)),
]
BASELINE = Mutant("baseline", "-", "no mutant", nullcontext)


class _Failures:
    def __init__(self) -> None:
        self.failed: list[str] = []

    def pytest_runtest_logreport(self, report) -> None:
        if report.failed:
            self.failed.append(report.nodeid)


def unit_failures(m: Mutant) -> list[str]:
    plugin = _Failures()
    with m.patch():
        pytest.main(["-q", "-p", "no:logging", "-p", "no:cacheprovider", "--no-header", "--tb=no",
                     str(ROOT / "tests" / "unit")], plugins=[plugin])
    return plugin.failed


def run_one(m: Mutant, bases, df, baseline_src: list[str] | None) -> tuple[dict, list[str] | None]:
    eng = mode_a_engine()
    row = {"id": m.id, "target": m.target, "change": m.change, "mrs": {}, "crash": None}
    row["unit_failed"] = unit_failures(m)
    print(f"{m.id}: {len(row['unit_failed'])} unit test(s) fail", flush=True)
    try:
        return _run_one(m, bases, df, baseline_src, eng, row)
    except Exception as e:  # a contract check in the application rejected the mutant's output
        row.update(changed=None, oracle_bases=None, idet=None, crash=f"{type(e).__name__}: {' '.join(str(e).split())[:140]}",
                   caught_by=[])
        print(f"{m.id}: run failed, {row['crash']}", flush=True)
        return row, None


def _run_one(m: Mutant, bases, df, baseline_src, eng, row) -> tuple[dict, list[str]]:
    with m.patch():
        src = [report_to_json(eng.run(b.to_criteria(), df, 0, RunOptions())) for b in bases]
        row["changed"] = 0 if baseline_src is None else sum(a != b for a, b in zip(src, baseline_src))
        oracle = idet = 0
        for name in MR_NAMES:
            r = run_mr(MRS[name], bases, df, eng.run, (0,), SeedRegistry(),
                       check_oracle=(name == "MR1"))  # the oracle depends only on the source run
            res = r.result()
            unc_v, unc_n = res.unconditioned
            row["mrs"][name] = {"violations": res.violations, "evaluated": res.evaluated,
                                "unconditioned": [unc_v, unc_n]}
            oracle += len({x["base_id"] for x in r.oracle_mismatches})
            idet += sum(v["invariant"] == "I-DET" for v in r.invariant_violations)
    row["oracle_bases"], row["idet"] = oracle, idet
    row["caught_by"] = [n for n, v in row["mrs"].items() if v["violations"]]
    print(f"{m.id}: changed {row['changed']}/{len(bases)}; oracle {oracle}; I-DET {idet}; "
          f"caught by {row['caught_by'] or 'no MR'}", flush=True)
    return row, src


def write_table(rows: list[dict], n: int, path: Path) -> None:
    head = ["Mutant", "Target", "Change", "Changed"] + MR_NAMES + ["Oracle", "I-DET", "Unit tests failing", "Caught by (MR)"]
    lines = [f"# Mutant detection (Mode A, {n} bases, seed 0)", "",
             "Each cell is conditioned violations / evaluated bases. *Changed* = bases whose source report "
             "differs from the baseline. *Oracle* = bases where the application disagrees with the oracle "
             "on its own `effective_criteria`. *Unit tests failing* = tests in `tests/unit` that fail under the "
             "mutant (listed in `detection.json`). Generated by `python -m tests.mt.mutants`.", "",
             "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        if r["crash"]:
            lines.append("| " + " | ".join([r["id"], f"`{r['target']}`", r["change"], "–", *["–"] * len(MR_NAMES),
                                             "–", "–", str(len(r["unit_failed"])),
                                             f"none; the run fails: `{r['crash']}`"]) + " |")
            continue
        cells = [f"{v['violations']}/{v['evaluated']}" if v["evaluated"] else "–" for v in r["mrs"].values()]
        lines.append("| " + " | ".join([r["id"], f"`{r['target']}`", r["change"], f"{r['changed']}/{n}",
                                         *cells, str(r["oracle_bases"]), str(r["idet"]), str(len(r["unit_failed"])),
                                         ", ".join(r["caught_by"]) or "**none**"]) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests.mt.mutants", description=__doc__.split("\n\n")[0])
    ap.add_argument("--bases", type=int, default=60)
    ap.add_argument("--mutant", action="append", choices=[m.id for m in MUTANTS])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    df = pd.read_csv(SNAPSHOT)
    bases = load_bases(ROOT / "results" / "bases_and_params.json")[: args.bases]
    base_row, base_src = run_one(BASELINE, bases, df, None)
    rows = [base_row] + [run_one(m, bases, df, base_src)[0]
                         for m in MUTANTS if not args.mutant or m.id in args.mutant]
    args.out.mkdir(parents=True, exist_ok=True)
    write_table(rows, len(bases), args.out / "detection_table.md")
    write_json({"n_bases": len(bases), "rows": rows}, args.out / "detection.json")
    print(f"written: {args.out / 'detection_table.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
