"""Diagnosis evidence for an MR (contracts/Testing.md 10.4, steps 2 and 3).

    uv run python -m tests.mt.diagnose --mr MR10                 # loops on vs off, all v0 bases
    uv run python -m tests.mt.diagnose --mr MR10 --bases 40      # first 40 bases only
    uv run python -m tests.mt.diagnose --mr MR10 --base-id 4     # trace diff for one base
    uv run python -m tests.mt.diagnose --mr MR3a --explain-gate  # MR3: diffs left with loops off vs the gate

Bases come from ``results/bases_and_params.json``, so the ids match the v0 run.

Loops mode runs the MR twice, with ``RunOptions.loops_enabled`` as the MR sets
it (on) and forced off in every run (off), and writes one row per base to
``<out>/<MR>_loops.csv``. For bases with diffs it also re-runs the pair to
record whether the soft filters in ``effective_criteria`` differ between the
source and any follow-up (different soft filters = the runs answered
different queries).

Gate mode (MR3a/MR3b, after loops mode) re-runs, with loops off, every base
that still differs and checks each diff against the ``MIN_BUCKET_N`` gate: a
``pct_change`` diff must sit at a month whose own or preceding ``ALL``
``n_in_bucket`` is 3 or 4 in the source (null there, 6 or 8 rows after
duplication). Anything else is printed as unexplained.

Trace mode writes ``<out>/<MR>_base<N>_trace.txt``: the effective criteria,
loop counters and trace events of the source and every follow-up (loops on).
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import pandas as pd

from plotline.contract import RunOptions
from tests.mt.generator import ROOT, SNAPSHOT, Base, load_bases
from tests.mt.harness import MR, oracle_diffs, report_dict, run_mr
from tests.mt.mrs import MRS
from tests.mt.run import mode_a_engine

BASES_FILE = ROOT / "results" / "bases_and_params.json"
OUT = ROOT / "results" / "diagnosis"
SOFT = ("price_band", "sqft_range", "sale_cond")


def loops_off_runner(run):
    def runner(query, df, seed, options):
        return run(query, df, seed, options.model_copy(update={"loops_enabled": False}))
    return runner


def pair_reports(mr: MR, base: Base, df: pd.DataFrame, run, seed: int = 0,
                 with_frames: bool = False) -> tuple[dict, list[dict]] | tuple[dict, list[dict], list[pd.DataFrame]]:
    """The source report and the follow-up reports, as ``run_mr`` builds them."""
    src = report_dict(run(mr.source(base), df, seed, RunOptions()))
    made = mr.transform(base, df)
    fus = made if isinstance(made, list) else [made]
    reports = [report_dict(run(fu.query, fu.df, seed, fu.options)) for fu in fus]
    return (src, reports, [fu.df for fu in fus]) if with_frames else (src, reports)


def soft(report: dict) -> dict:
    eff = report.get("effective_criteria") or {}
    return {k: eff.get(k) for k in SOFT}


def l2(report: dict) -> int:
    return report["metadata"]["loop_counters"]["L2_attempts"]


def loops(mr: MR, bases: list[Base], df: pd.DataFrame, out: Path) -> Path:
    eng = mode_a_engine()
    on = {p.base_id: p for p in run_mr(mr, bases, df, eng.run, (0,), check_invariants=False).pairs}
    off = {p.base_id: p for p in
           run_mr(mr, bases, df, loops_off_runner(eng.run), (0,), check_invariants=False).pairs}
    by_id = {b.base_id: b for b in bases}
    rows = []
    for bid in sorted(on):
        a, b = on[bid], off[bid]
        row = dict(base_id=bid, n_rows=by_id[bid].n_rows,
                   outcome_on=a.outcome, reason_on=a.reason, n_diffs_on=len(a.diffs),
                   outcome_off=b.outcome, reason_off=b.reason, n_diffs_off=len(b.diffs),
                   l2_src=None, l2_fu_max=None, soft_filters_differ=None)
        if a.diffs:
            src, fus = pair_reports(mr, by_id[bid], df, eng.run)
            row.update(l2_src=l2(src), l2_fu_max=max(l2(f) for f in fus),
                       soft_filters_differ=any(soft(f) != soft(src) for f in fus))
        rows.append(row)

    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{mr.name}_loops.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    with_on = [r for r in rows if r["n_diffs_on"]]
    still = [r["base_id"] for r in with_on if r["n_diffs_off"]]
    only_off = [r["base_id"] for r in rows if r["n_diffs_off"] and not r["n_diffs_on"]]
    differ = sum(bool(r["soft_filters_differ"]) for r in with_on)
    print(f"{mr.name}: {len(rows)} bases; {len(with_on)} with diffs (loops on); "
          f"{len(still)} of those still differ with loops off; "
          f"{differ} of {len(with_on)} have different soft filters in effective_criteria")
    print(f"  still differ with loops off: {still}")
    print(f"  differ only with loops off: {only_off}")
    print(f"  written: {path}")
    return path


def explain_gate(mr: MR, df: pd.DataFrame, out: Path) -> int:
    rows = pd.read_csv(out / f"{mr.name}_loops.csv")
    ids = rows[rows.n_diffs_off > 0].base_id.tolist()
    by_id = {b.base_id: b for b in load_bases(BASES_FILE)}
    run = loops_off_runner(mode_a_engine().run)
    kinds: dict[str, int] = {}
    unexplained = []
    for bid in ids:
        src, fus = pair_reports(mr, by_id[bid], df, run)
        n = {r["month"]: r["n_in_bucket"] for r in src["records"] if r["region_key"] == "ALL"}
        months = sorted(n)
        for d in mr.check(src, fus[0], by_id[bid]):
            if ".pct_change" in d.field:
                m = d.field.split(".")[1].split("/")[0]
                low = min(n[m], n[months[months.index(m) - 1]])
                kind = "pct_change at a month (or predecessor) with n in {3,4}" if low in (3, 4) else None
            elif d.field == "anomaly_flags":
                kind = "anomaly_flags (follow from pct_change / count_drop on the same months)"
            elif d.field.startswith("summary"):
                kind = "summary (pooled first-3/last-3 gate)"
            else:
                kind = None
            if kind is None:
                unexplained.append((bid, d.field))
            else:
                kinds[kind] = kinds.get(kind, 0) + 1
    print(f"{mr.name}: {len(ids)} bases still differ with loops off")
    for k, v in kinds.items():
        print(f"  {v:>5}  {k}")
    print(f"  unexplained: {len(unexplained)} {unexplained[:20]}")
    return len(unexplained)


def _events(report: dict) -> list[str]:
    return [f"  [{e['i']:>2}] {e['agent']:<10} {e['kind']:<8} {e['loop'] or '':<3} {e['msg']}"
            for e in report["trace"]]


def trace(mr: MR, base: Base, df: pd.DataFrame, out: Path) -> Path:
    src, fus, frames = pair_reports(mr, base, df, mode_a_engine().run, with_frames=True)
    lines = [f"{mr.name} base {base.base_id} ({base.stratum}, {base.n_rows} matching rows), loops on",
             f"base criteria: {base.criteria}", f"MR params: {base.params.get(mr.name)}", ""]
    runs = [("SOURCE", src, df), *[(f"FOLLOW-UP {i}", f, fr) for i, (f, fr) in enumerate(zip(fus, frames))]]
    for label, rep, frame in runs:
        mism = oracle_diffs(rep, frame)  # the oracle on this run's own effective_criteria and frame
        lines += [f"== {label}: status={rep['status']} loop_counters={rep['metadata']['loop_counters']} "
                  f"oracle_mismatches={len(mism)}",
                  f"effective_criteria: {rep.get('effective_criteria')}", *_events(rep),
                  *[f"  ORACLE MISMATCH {d.field}: app={d.source_value} oracle={d.follow_up_value}" for d in mism],
                  ""]
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{mr.name}_base{base.base_id}_trace.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"written: {path}")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests.mt.diagnose", description=__doc__.split("\n\n")[0])
    ap.add_argument("--mr", action="append", required=True, choices=sorted(MRS))
    ap.add_argument("--bases", type=int, default=None, help="first N bases (default: all)")
    ap.add_argument("--base-id", type=int, action="append", help="write the trace diff for this base")
    ap.add_argument("--explain-gate", action="store_true", help="MR3: check the loops-off diffs against the gate")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    df = pd.read_csv(SNAPSHOT)
    bases = load_bases(BASES_FILE)
    for name in args.mr:
        if args.explain_gate:
            explain_gate(MRS[name], df, args.out)
        elif args.base_id:
            for bid in args.base_id:
                trace(MRS[name], next(b for b in bases if b.base_id == bid), df, args.out)
        else:
            loops(MRS[name], bases[: args.bases], df, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
