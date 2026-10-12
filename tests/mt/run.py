"""Run metamorphic relations and write the result files (contracts/Testing.md 7-9).

    uv run python -m tests.mt.run                 # every MR, 100 bases, Mode A
    uv run python -m tests.mt.run --mr MR1 --bases 60

Mode A: ``LLM_MODE=off``, one run per base with ``seed = 0``, the
determinism self-test (I-DET) and I-PURE on every base, and the application
checked against the oracle on every base. The bases regenerate from
``GEN_SEED``. Writes into ``results/``:

    violations.csv        MR, base_id, seed, field, source_value, follow_up_value
    skips.csv             MR, base_id, seed, reason (a skip is not a pass)
    headline_table.md     one row per MR (stats.headline_table)
    bases_and_params.json the bases and every MR's drawn parameters
    run_manifest.json     snapshot hash, versions, seeds, counts, invariant and oracle results

Exit status 1 when the snapshot hash does not match, the application
disagrees with the oracle, or an invariant fails: those must be fixed before
MR results mean anything (Testing.md 2.3.3). MR violations are results, not
failures of this command.
"""

from __future__ import annotations

import argparse
import csv
import platform
import sys
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from plotline.contract import CONTRACT_VERSION, GEN_SEED
from plotline.llm_client import LlmClient, LlmConfig
from plotline.orchestrator import Engine, detect_logic_version
from plotline.snapshot import check_snapshot
from tests.mt.generator import ROOT, SNAPSHOT, generate, save_bases
from tests.mt.harness import SeedRegistry, run_mr, write_json, write_violations
from tests.mt.mrs import MRS
from tests.mt.stats import write_headline_table

RESULTS = ROOT / "results"
MODE_A_SEEDS = (0,)
MAX_LISTED = 50  # oracle mismatches listed in the manifest (all are counted)


def mode_a_engine() -> Engine:
    """The application with the model off, whatever ``.env`` says (Mode A)."""
    return Engine.from_data_dir(ROOT / "data", llm_client=LlmClient(LlmConfig(mode="off")),
                                logic_version=detect_logic_version())


def write_skips(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=("MR", "base_id", "seed", "reason"))
        w.writeheader()
        w.writerows(rows)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests.mt.run", description=__doc__.split("\n\n")[0])
    ap.add_argument("--mr", action="append", choices=sorted(MRS), help="MR to run (repeatable; default: all)")
    ap.add_argument("--bases", type=int, default=100, help="number of bases (default 100)")
    ap.add_argument("--out", type=Path, default=RESULTS, help="results directory")
    args = ap.parse_args(argv)

    sha, err = check_snapshot(SNAPSHOT, ROOT / "data" / "SNAPSHOT.sha256")
    if err:
        print(f"E_SNAPSHOT_HASH: {err}", file=sys.stderr)
        return 1
    df = pd.read_csv(SNAPSHOT)
    bases = generate(df, args.bases)
    save_bases(bases, args.out / "bases_and_params.json", snapshot_sha256=sha)
    engine = mode_a_engine()
    registry = SeedRegistry()

    runs = []
    for name in args.mr or sorted(MRS):
        print(f"{name}: {len(bases)} bases ...", flush=True)
        runs.append(run_mr(MRS[name], bases, df, engine.run, MODE_A_SEEDS, registry, check_oracle=True))

    write_violations([row for r in runs for row in r.violation_rows()], args.out / "violations.csv")
    write_skips([row for r in runs for row in r.skip_rows()], args.out / "skips.csv")
    results = [r.result() for r in runs]
    write_headline_table(results, args.out / "headline_table.md", title="Headline results (Mode A, LLM_MODE=off)")
    invariants = [v | {"MR": r.mr.name} for r in runs for v in r.invariant_violations]
    mismatches = [m | {"MR": r.mr.name} for r in runs for m in r.oracle_mismatches]
    write_json({
        "mode": "A", "llm_mode": "off", "llm": None,
        "snapshot_sha256": sha, "contract_version": CONTRACT_VERSION, "git_commit": engine.logic_version,
        "gen_seed": GEN_SEED, "seeds": list(MODE_A_SEEDS), "n_bases": len(bases),
        "strata": {s: sum(b.stratum == s for b in bases) for s in ("broad", "thin")},
        "seed_registry_entries": len(registry.entries),
        "mrs": {r.mr: {"evaluated": r.evaluated, "violations": r.violations, "skipped": r.n_skipped} for r in results},
        "invariant_violations": invariants,
        "oracle_mismatches": {"count": len(mismatches), "first": mismatches[:MAX_LISTED]},
        "versions": {"python": platform.python_version(),
                     **{p: version(p) for p in ("pandas", "numpy", "pydantic", "scipy")}},
    }, args.out / "run_manifest.json")

    for r in results:
        print(f"{r.mr}: {r.violations} violating of {r.evaluated} evaluated, {r.n_skipped} skipped")
    print(f"invariant violations: {len(invariants)}; oracle mismatches: {len(mismatches)}; results in {args.out}")
    return 1 if invariants or mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
