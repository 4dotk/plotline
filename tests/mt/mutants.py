"""Mutant testing: plant known bugs in the agents and see which test layer catches them.

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

``freetext`` runs the three sentence sets (tests/smoke_queries, tests/nl_eval_queries,
tests/nl_l1_scenarios) through the AI-mode path with the model stubbed (rule
parser) and counts sentences that are read right without the mutant but not with
it. M1-M5 sit in the Aggregator and Validator, M6-M16 in the Planner, its rule
parser and the Inspector (1.2.0), where the faults found on 10-16 were.

A mutant is *killed* by a layer when that layer reports at least one failure.
``<out>/scores.md`` gives the mutation score per layer.

Writes ``<out>/detection_table.md`` and ``<out>/detection.json``.
"""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ProcessPoolExecutor
import importlib
import importlib.util
import re
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from unittest import mock

import numpy as np
import pandas as pd
import pytest

from plotline.contract import ALL_REGION, MIN_BUCKET_N, RunOptions, TrendRecord
from plotline.agents import aggregator, inspector, nl_rules, planner, validator
from plotline.llm_client import LlmClient
from plotline.orchestrator import Engine
from tests.mt.generator import ROOT, SNAPSHOT, load_bases
from tests.mt.harness import SeedRegistry, report_to_json, run_mr, write_json
from tests.mt.mrs import MRS
from tests.mt.mrs.mr09_paraphrase import with_phrasings
from tests.mt.run import mode_a_engine, rules_engine
from tests.support import FakeChat, llm_config

OUT = ROOT / "results" / "mutants"
MR_NAMES = sorted(MRS, key=lambda s: (int(s[2:].rstrip("ab")), s))  # MR9 runs through the rule parser


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


_ORIG_REPAIR_ONE = planner._repair_one
_ORIG_VALIDATE = aggregator.validate_criteria


def m12_repair_one(issue, eff, info):
    if issue == "band_inverted":
        return list(eff.price_band)  # was: swapped
    return _ORIG_REPAIR_ONE(issue, eff, info)


def m13_repair_one(issue, eff, info):
    if issue == "window_out_of_range":
        return info.latest_month  # was: clamped to the nearest end (an early year went to the first valid end)
    return _ORIG_REPAIR_ONE(issue, eff, info)


def m16_validate(effective, info):
    out = _ORIG_VALIDATE(effective, info)  # the Inspector forgets the data's month range
    if out is not None and not isinstance(out, aggregator.Failure) and out.issues == ["window_out_of_range"]:
        return None
    return out


_NEVER = re.compile(r"(?!)")
_OLD_BHK = re.compile(r"((?:\b\d\b\s*(?:,|/|or|and|&|-|to)?\s*)+)\s*(?:bhk|bed(?:room)?s?|br)\b")


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
    Mutant("M6", "nl_rules._BHK", "BHK needs a space before 'bhk' again (\"2bhk\" dropped, F2)",
           lambda: mock.patch.object(nl_rules, "_BHK", _OLD_BHK)),
    Mutant("M7", "nl_rules._unit_factor", "a crore is read as a lakh",
           lambda: mock.patch.object(nl_rules, "_unit_factor", lambda w: 100_000)),
    Mutant("M8", "nl_rules._OTHER_PLACES", "places outside the data are dropped (query becomes all 7)",
           lambda: mock.patch.object(nl_rules, "_OTHER_PLACES", {})),
    Mutant("M9", "nl_rules._EXCLUDE", "\"except X\" is ignored",
           lambda: mock.patch.object(nl_rules, "_EXCLUDE", _NEVER)),
    Mutant("M10", "nl_rules._FUZZY_CUTOFF", "close spellings are not matched",
           lambda: mock.patch.object(nl_rules, "_FUZZY_CUTOFF", 1.0)),  # exact only (1.01 made difflib raise: invalid)
    Mutant("M11", "planner._audit", "no parse-audit warning for a filter that was not read",
           lambda: mock.patch.object(planner, "_audit", lambda sentence, criteria, trace: criteria)),
    Mutant("M12", "planner._repair_one", "L1 does not swap an inverted band",
           lambda: mock.patch.object(planner, "_repair_one", m12_repair_one)),
    Mutant("M13", "planner._repair_one", "L1 clamps every window to the latest month",
           lambda: mock.patch.object(planner, "_repair_one", m13_repair_one)),
    Mutant("M14", "inspector.no_sales", "no notice when a locality has no sales",
           lambda: mock.patch.object(inspector, "no_sales", lambda *a, **k: [])),
    Mutant("M15", "inspector._repair_notices", "L1 repairs are not told to the user",
           lambda: mock.patch.object(inspector, "_repair_notices", lambda *a, **k: [])),
    Mutant("M16", "inspector.validate_criteria", "the Inspector ignores the data's month range",
           lambda: mock.patch.object(inspector, "validate_criteria", m16_validate)),
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


_SMOKE = None


def _judge():
    global _SMOKE
    if _SMOKE is None:
        spec = importlib.util.spec_from_file_location("smoke", ROOT / "scripts" / "smoke_20_queries.py")
        _SMOKE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_SMOKE)
    return _SMOKE.judge


SENTENCE_SETS = ("tests.smoke_queries", "tests.nl_eval_queries", "tests.nl_l1_scenarios")


def freetext_passing(m: Mutant, df) -> set[str]:
    """Sentences read right under the mutant (AI-mode path, model stubbed to fail -> rule parser)."""
    judge = _judge()
    eng = Engine.from_data_dir(ROOT / "data", llm_client=LlmClient(llm_config("live"), chat=FakeChat("not json")))
    ok = set()
    with m.patch():
        for mod in SENTENCE_SETS:
            for sentence, expected, _ in importlib.import_module(mod).QUERIES:
                try:
                    if judge(eng.run(sentence, df, 0, RunOptions()), expected)[0]:
                        ok.add(sentence)
                except Exception:  # a contract check rejected the mutant's report: not read right
                    pass
    return ok


_FREETEXT_BASE: set[str] = set()


def run_one(m: Mutant, bases, df, baseline_src: list[str] | None) -> tuple[dict, list[str] | None]:
    eng = mode_a_engine()
    row = {"id": m.id, "target": m.target, "change": m.change, "mrs": {}, "crash": None}
    row["unit_failed"] = unit_failures(m)
    passing = freetext_passing(m, df)
    if m.id == "baseline":
        _FREETEXT_BASE.clear()
        _FREETEXT_BASE.update(passing)
    row["freetext_failed"] = sorted(_FREETEXT_BASE - passing)
    print(f"{m.id}: {len(row['unit_failed'])} unit test(s) fail; "
          f"{len(row['freetext_failed'])} sentence(s) no longer read right", flush=True)
    try:
        return _run_one(m, bases, df, baseline_src, eng, row)
    except Exception as e:  # a contract check in the application rejected the mutant's output
        row.update(changed=None, oracle_bases=None, idet=None, crash=f"{type(e).__name__}: {' '.join(str(e).split())[:140]}",
                   caught_by=[])
        print(f"{m.id}: run failed, {row['crash']}", flush=True)
        return row, None


def _run_one(m: Mutant, bases, df, baseline_src, eng, row) -> tuple[dict, list[str]]:
    rules = rules_engine()
    with m.patch():
        src = [report_to_json(eng.run(b.to_criteria(), df, 0, RunOptions())) for b in bases]
        row["changed"] = 0 if baseline_src is None else sum(a != b for a, b in zip(src, baseline_src))
        oracle = idet = 0
        for name in MR_NAMES:
            r = run_mr(MRS[name], bases, df, rules.run if name == "MR9" else eng.run, (0,), SeedRegistry(),
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


def _worker(mutant_id: str, n_bases: int, base_src: list[str], freetext_base: list[str]) -> dict:
    # pytest's conftest recreates its log directory every session: parallel workers need their own,
    # or they delete each other's logs and pytest fails with INTERNALERROR (found 10-17)
    import tempfile
    os.environ["PLOTLINE_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix=f"plotline-{mutant_id}-")
    df = pd.read_csv(SNAPSHOT)
    bases = with_phrasings(load_bases(ROOT / "results" / "bases_and_params.json")[:n_bases], df)
    _FREETEXT_BASE.clear()
    _FREETEXT_BASE.update(freetext_base)
    return run_one(next(m for m in MUTANTS if m.id == mutant_id), bases, df, base_src)[0]


def killed(r: dict) -> dict[str, bool]:
    mt = bool(r["caught_by"]) or bool(r.get("oracle_bases")) or bool(r.get("idet"))
    return {"unit tests": bool(r["unit_failed"]), "MRs + oracle (MT)": mt,
            "free-text set": bool(r["freetext_failed"]), "contract checks (run rejected)": bool(r["crash"])}


def write_scores(rows: list[dict], n: int, path: Path) -> None:
    muts = [r for r in rows if r["id"] != "baseline"]
    layers = list(killed(muts[0]))
    lines = [f"# Mutation score by test layer ({len(muts)} mutants; MT on {n} bases, Mode A)", "",
             "A mutant is killed by a layer when the layer reports at least one failure under it. "
             "Generated by `python -m tests.mt.mutants`.", "",
             "| Mutant | Change | " + " | ".join(layers) + " | any |", "|---|---|" + "---|" * (len(layers) + 1)]
    for r in muts:
        k = killed(r)
        lines.append(f"| {r['id']} | {r['change']} | " + " | ".join("✔" if k[l] else "" for l in layers)
                     + f" | {'✔' if any(k.values()) else '**survived**'} |")
    score = lambda pred: f"{sum(pred(r) for r in muts)}/{len(muts)}"  # noqa: E731
    lines.append("| **score** | | " + " | ".join(score(lambda r, l=l: killed(r)[l]) for l in layers)
                 + f" | {score(lambda r: any(killed(r).values()))} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests.mt.mutants", description=__doc__.split("\n\n")[0])
    ap.add_argument("--bases", type=int, default=60)
    ap.add_argument("--mutant", action="append", choices=[m.id for m in MUTANTS])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2),
                    help="mutants run in parallel processes (default: half the cores)")
    args = ap.parse_args(argv)

    df = pd.read_csv(SNAPSHOT)
    bases = with_phrasings(load_bases(ROOT / "results" / "bases_and_params.json")[: args.bases], df)
    base_row, base_src = run_one(BASELINE, bases, df, None)
    todo = [m.id for m in MUTANTS if not args.mutant or m.id in args.mutant]
    # each mutant is independent: one process each (patches stay inside their own process)
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        rows = [base_row] + list(pool.map(_worker, todo, [args.bases] * len(todo), [base_src] * len(todo),
                                          [sorted(_FREETEXT_BASE)] * len(todo)))
    args.out.mkdir(parents=True, exist_ok=True)
    write_table(rows, len(bases), args.out / "detection_table.md")
    write_scores(rows, len(bases), args.out / "scores.md")
    write_json({"n_bases": len(bases), "rows": rows}, args.out / "detection.json")
    print(f"written: {args.out / 'detection_table.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
