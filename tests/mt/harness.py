"""Metamorphic-test harness core (contracts/Testing.md sections 1-3, 5, 6, 9, T22).

For each base input and seed: run the source, build the follow-up by one named
transformation, run it, compare the two reports with the section 3 comparators
and record pass / violation / skip. Every seed used goes into a ``SeedRegistry``.

The harness calls only the entry point ``run(...)`` (any ``Runner``) and reads
only report fields (Testing.md 1). On every base it also checks the free
invariants I-DET and I-PURE and, when asked, the application against the
independent oracle (Testing.md 2.3, 2.5).

Rules from Testing.md 5.2-6:
* source report not ``ok`` on a generated base -> ``HarnessError`` (stop: a
  generator, oracle or contract bug, not an MR result);
* follow-up not ``ok`` -> a violation on field ``status``, never a skip;
* a skip is not a pass. ``precondition`` skips (the transformation is undefined)
  are never waived; ``skip`` rules (report fields) are waived in the
  unconditioned column;
* several seeds (Mode B): a base violates if any of its seeds violates.
"""

from __future__ import annotations

import csv
import hashlib
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Union

import pandas as pd

from plotline.contract import (
    ABS_TOL,
    ABS_TOL_PCT,
    REL_TOL,
    Criteria,
    RunOptions,
    TrendReport,
    canonical_criteria_json,
    report_to_json,
)
from tests.mt.generator import Base
from tests.mt.oracle import oracle
from tests.mt.stats import MRResult

Runner = Callable[[Union[Criteria, str], pd.DataFrame, int, RunOptions], TrendReport]
VIOLATION_COLUMNS = ("MR", "base_id", "seed", "field", "source_value", "follow_up_value")  # Testing.md 9
PRECONDITION = "precondition: "  # prefix of skip reasons that are never waived


class HarnessError(RuntimeError):
    """A run the harness cannot use: stop, do not count it."""


# ---------------------------------------------------------------------------
# Comparators (Testing.md 3). None equals only None.
# ---------------------------------------------------------------------------


def exact(a: Any, b: Any) -> bool:
    return a == b


def bit_exact(a: Any, b: Any) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return (isinstance(a, float) and isinstance(b, float)
                and struct.pack("<d", a) == struct.pack("<d", b))
    return a == b


def _numeric(close: Callable[[float, float], bool]) -> Callable[[Any, Any], bool]:
    def compare(a: Any, b: Any) -> bool:
        if a is None or b is None:
            return a is None and b is None
        return close(float(a), float(b))
    return compare


rel_tol = _numeric(lambda a, b: abs(a - b) <= REL_TOL * max(abs(a), abs(b)))
abs_tol = _numeric(lambda a, b: abs(a - b) <= ABS_TOL)
abs_tol_pct = _numeric(lambda a, b: abs(a - b) <= ABS_TOL_PCT)


@dataclass(frozen=True)
class Diff:
    """One violated field; ``field`` names it (Testing.md 9)."""

    field: str
    source_value: Any
    follow_up_value: Any


def report_dict(report: TrendReport) -> dict:
    """The report as plain JSON values; floats round-trip bit-exactly."""
    return json.loads(report_to_json(report))


def keyed(report: dict) -> dict:
    """``records`` and ``anomaly_flags`` keyed by identity: consumers never rely on order."""
    out = dict(report)
    if "records" in out:
        out["records"] = {f"{r['month']}/{r['region_key']}": r for r in out["records"]}
    if "anomaly_flags" in out:
        out["anomaly_flags"] = {f"{f['month']}/{f['region_key']}/{f['kind']}": f for f in out["anomaly_flags"]}
    return out


def diff(a: Any, b: Any, cmp: Callable[[Any, Any], bool] = exact, path: str = "") -> list[Diff]:
    """Every leaf where ``a`` and ``b`` differ under ``cmp`` (dicts by key, lists by position)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[Diff] = []
        for k in sorted(set(a) | set(b), key=str):
            p = f"{path}.{k}" if path else str(k)
            if k not in a or k not in b:
                out.append(Diff(p, a.get(k, "<missing>"), b.get(k, "<missing>")))
            else:
                out += diff(a[k], b[k], cmp, p)
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in diff(x, y, cmp, f"{path}[{i}]")]
    return [] if cmp(a, b) else [Diff(path, a, b)]


# ---------------------------------------------------------------------------
# Application against the oracle (Testing.md 2.3.2)
# ---------------------------------------------------------------------------

_RECORD_CMP = {
    "listing_count": exact, "n_in_bucket": exact, "low_sample": exact,
    "median_price": rel_tol, "median_price_per_sqft": rel_tol, "pct_change_price_per_sqft": abs_tol,
}


def oracle_diffs(report: dict, df: pd.DataFrame) -> list[Diff]:
    """Where an ok report disagrees with the oracle on its own ``effective_criteria``.
    ``source_value`` is the application's value, ``follow_up_value`` the oracle's."""
    app, exp = keyed(report), keyed(oracle(df, report["effective_criteria"]))
    out: list[Diff] = []
    if set(app["records"]) != set(exp["records"]):  # I-DENSE
        out.append(Diff("records.keys", sorted(app["records"]), sorted(exp["records"])))
    for k in sorted(set(app["records"]) & set(exp["records"])):
        for f, cmp in _RECORD_CMP.items():
            out += diff(app["records"][k][f], exp["records"][k][f], cmp, f"records.{k}.{f}")
    out += diff(app["coverage_score"], exp["coverage_score"], exact, "coverage_score")
    if set(app["anomaly_flags"]) != set(exp["anomaly_flags"]):
        out.append(Diff("anomaly_flags", sorted(app["anomaly_flags"]), sorted(exp["anomaly_flags"])))
    for k in sorted(set(app["anomaly_flags"]) & set(exp["anomaly_flags"])):
        out += diff(app["anomaly_flags"][k]["value"], exp["anomaly_flags"][k]["value"], rel_tol,
                    f"anomaly_flags.{k}.value")
    out += diff(app["summary"]["n_rows"], exp["summary"]["n_rows"], exact, "summary.n_rows")
    for stat in ("price", "price_per_sqft"):
        a, e = app["summary"][stat], exp["summary"][stat]
        if (a is None) != (e is None):
            out.append(Diff(f"summary.{stat}", a, e))
        elif a is not None:
            for f, cmp in (("start", rel_tol), ("end", rel_tol), ("change_pct", abs_tol_pct), ("direction", exact)):
                out += diff(a[f], e[f], cmp, f"summary.{stat}.{f}")
    return out


# ---------------------------------------------------------------------------
# MRs, seeds, outcomes
# ---------------------------------------------------------------------------


class SeedRegistry:
    """Every seed the harness uses, with what it was used for (Testing.md 11, T22)."""

    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, purpose: str, base_id: int | None, seed: int) -> int:
        self.entries.append({"purpose": purpose, "base_id": base_id, "seed": seed})
        return seed

    def seeds(self, purpose: str | None = None) -> list[int]:
        return [e["seed"] for e in self.entries if purpose is None or e["purpose"] == purpose]


@dataclass(frozen=True)
class FollowUp:
    query: Union[Criteria, str]
    df: pd.DataFrame
    options: RunOptions = field(default_factory=RunOptions)
    seeds: dict[str, int] = field(default_factory=dict)  # seeds the transformation used, by purpose


@dataclass(frozen=True)
class MR:
    """One metamorphic relation. ``transform`` builds a new frame and never
    touches the source (I-PURE); ``check`` returns the violated fields.

    When ``transform`` returns a list (MR9 phrasings, MR10 one run per BHK),
    ``check`` and ``skip`` get the list of follow-up reports in the same order."""

    name: str
    family: str
    transform: Callable[[Base, pd.DataFrame], Union[FollowUp, list[FollowUp]]]
    check: Callable[[dict, Any, Base], list[Diff]]
    precondition: Callable[[Base, pd.DataFrame], str | None] = lambda base, df: None
    skip: Callable[[dict, Any, Base], str | None] = lambda src, fu, base: None
    source: Callable[[Base], Union[Criteria, str]] = Base.to_criteria  # the source query
    # a skip rule decidable on the source report alone, checked before the "source not ok" stop
    # (MR9: a sentence query is E_LLM_OFF by design when LLM_MODE=off, and its rule skips it)
    source_skip: Callable[[dict], str | None] = lambda src: None


@dataclass
class PairOutcome:
    base_id: int
    seed: int
    outcome: str  # "pass", "violation" or "skip"
    reason: str | None = None
    diffs: list[Diff] = field(default_factory=list)  # kept for skips too (unconditioned column)


_RANK = {"skip": 0, "pass": 1, "violation": 2}


@dataclass
class MRRun:
    mr: MR
    n_bases: int
    seeds: tuple[int, ...]
    pairs: list[PairOutcome] = field(default_factory=list)
    invariant_violations: list[dict] = field(default_factory=list)  # I-DET, I-PURE
    oracle_mismatches: list[dict] = field(default_factory=list)

    def base_outcomes(self) -> dict[int, PairOutcome]:
        """Per base: violation if any seed violates; skip only if every seed skipped."""
        out: dict[int, PairOutcome] = {}
        for p in self.pairs:
            if p.base_id not in out or _RANK[p.outcome] > _RANK[out[p.base_id].outcome]:
                out[p.base_id] = p
        return out

    def violation_rows(self) -> list[dict]:
        return [dict(MR=self.mr.name, base_id=p.base_id, seed=p.seed, field=d.field,
                     source_value=d.source_value, follow_up_value=d.follow_up_value)
                for p in self.pairs if p.outcome == "violation" for d in p.diffs]

    def waived_rows(self) -> list[dict]:
        """Diffs inside report-field skips (the unconditioned column), with the skip reason."""
        return [dict(MR=self.mr.name, base_id=p.base_id, seed=p.seed, field=d.field, source_value=d.source_value,
                     follow_up_value=d.follow_up_value, reason=p.reason)
                for p in self.pairs if p.outcome == "skip" for d in p.diffs]

    def skip_rows(self) -> list[dict]:
        return [dict(MR=self.mr.name, base_id=p.base_id, seed=p.seed, reason=p.reason)
                for p in self.pairs if p.outcome == "skip"]

    def unconditioned(self) -> tuple[int, int]:
        """(violating, evaluated) bases with report-field skips waived (Testing.md 6)."""
        per_base: dict[int, bool] = {}
        for p in self.pairs:
            if p.outcome == "skip" and (p.reason or "").startswith(PRECONDITION):
                continue
            per_base[p.base_id] = per_base.get(p.base_id, False) or bool(p.diffs)
        return sum(per_base.values()), len(per_base)

    def result(self) -> MRResult:
        bases = self.base_outcomes()
        skipped: dict[str, int] = {}
        for b in bases.values():
            if b.outcome == "skip":
                skipped[b.reason or "?"] = skipped.get(b.reason or "?", 0) + 1
        evaluated = [p for p in self.pairs if p.outcome != "skip"]
        mode_b = len(self.seeds) > 1
        return MRResult(
            mr=self.mr.name, family=self.mr.family, seeds=self.seeds, n_bases=self.n_bases,
            violations=sum(b.outcome == "violation" for b in bases.values()), skipped=skipped,
            pairs=len(evaluated) if mode_b else None,
            pair_violations=sum(p.outcome == "violation" for p in evaluated) if mode_b else None,
            unconditioned=self.unconditioned(),
        )


def frame_hash(df: pd.DataFrame) -> str:
    """Content hash of a frame (values, index, columns, dtypes) for I-PURE."""
    h = hashlib.sha256()
    h.update(json.dumps([list(map(str, df.columns)), [str(t) for t in df.dtypes]]).encode())
    h.update(pd.util.hash_pandas_object(df, index=True).to_numpy().tobytes())
    return h.hexdigest()


def run_mr(
    mr: MR,
    bases: Iterable[Base],
    df: pd.DataFrame,
    runner: Runner,
    seeds: tuple[int, ...] = (0,),
    registry: SeedRegistry | None = None,
    check_invariants: bool = True,
    check_oracle: bool = False,
) -> MRRun:
    registry = registry if registry is not None else SeedRegistry()
    bases = list(bases)
    out = MRRun(mr=mr, n_bases=len(bases), seeds=tuple(seeds))
    df_hash = frame_hash(df)

    for base in bases:
        pre = mr.precondition(base, df)
        for seed in seeds:
            if pre is not None:
                out.pairs.append(PairOutcome(base.base_id, seed, "skip", PRECONDITION + pre))
                continue
            registry.record("run", base.base_id, seed)
            criteria = mr.source(base)
            crit_json = criteria if isinstance(criteria, str) else canonical_criteria_json(criteria)
            src = runner(criteria, df, seed, RunOptions())
            early = mr.source_skip(report_dict(src))
            if early is not None:
                out.pairs.append(PairOutcome(base.base_id, seed, "skip", early))
                continue
            if src.status != "ok":
                raise HarnessError(f"{mr.name} base {base.base_id}: source report is "
                                   f"{src.status} ({src.error.code if src.error else None})")
            src_d = report_dict(src)

            if check_invariants:
                if report_to_json(runner(criteria, df, seed, RunOptions())) != report_to_json(src):
                    out.invariant_violations.append(dict(invariant="I-DET", base_id=base.base_id, seed=seed))
                if frame_hash(df) != df_hash or (
                        not isinstance(criteria, str) and canonical_criteria_json(criteria) != crit_json):
                    out.invariant_violations.append(dict(invariant="I-PURE", base_id=base.base_id, seed=seed))
            if check_oracle and seed == seeds[0]:
                out.oracle_mismatches += [
                    dict(base_id=base.base_id, field=d.field, application=d.source_value, oracle=d.follow_up_value)
                    for d in oracle_diffs(src_d, df)
                ]

            made = mr.transform(base, df)
            fus = made if isinstance(made, list) else [made]
            if any(fu.df is df for fu in fus) or frame_hash(df) != df_hash:
                raise HarnessError(f"{mr.name}: a transformation must return a new frame and keep the source")
            for fu in fus:
                for purpose, s in fu.seeds.items():
                    registry.record(f"{mr.name} {purpose}", base.base_id, s)
            fu_ds = [report_dict(runner(fu.query, fu.df, seed, fu.options)) for fu in fus]

            not_ok = [(i, d) for i, d in enumerate(fu_ds) if d["status"] != "ok"]
            if not_ok:
                diffs = [Diff(f"follow_up[{i}].status" if isinstance(made, list) else "status",
                              src_d["status"], d["status"]) for i, d in not_ok]
                reason = None
            else:
                fu_d = fu_ds if isinstance(made, list) else fu_ds[0]
                diffs, reason = mr.check(src_d, fu_d, base), mr.skip(src_d, fu_d, base)
            outcome = "skip" if reason is not None else ("violation" if diffs else "pass")
            out.pairs.append(PairOutcome(base.base_id, seed, outcome, reason, diffs))
    return out


# ---------------------------------------------------------------------------
# Result files (Testing.md 9)
# ---------------------------------------------------------------------------


def _cell(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v, separators=(",", ":"), sort_keys=True)


def write_violations(rows: list[dict], path: str | Path, extra: tuple[str, ...] = ()) -> Path:
    """``results/violations.csv`` with exactly the contract's columns (plus ``extra`` for raw logs)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=VIOLATION_COLUMNS + extra)
        w.writeheader()
        for r in rows:
            w.writerow({k: _cell(r[k]) for k in VIOLATION_COLUMNS + extra})
    return p


def write_json(obj: Any, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return p
