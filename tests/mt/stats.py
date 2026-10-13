"""Violation-rate statistics and the headline table (contracts/Testing.md sections 6, 8, 9).

* Violation rate = violating bases / evaluated (non-skipped) bases.
* 95 % interval: Wilson score (z = 1.96); Clopper-Pearson when the violation
  count is 0 or n. For 0 of n the upper bound is ``1 - 0.025 ** (1 / n)``.
* ``headline_table`` renders ``results/headline_table.md``: one row per MR,
  with skips per reason, Mode B per-pair rates, and the unconditioned column
  for MRs 3, 5, 6, 7 and 10.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from scipy.stats import beta, norm

CONFIDENCE = 0.95
UNCONDITIONED_MRS = ("3a", "3b", "5", "6", "7", "10")  # Testing.md 6


@dataclass(frozen=True)
class Interval:
    lo: float
    hi: float
    method: str  # "Wilson" or "Clopper-Pearson"


def wilson(k: int, n: int, confidence: float = CONFIDENCE) -> Interval:
    z = float(norm.ppf(1 - (1 - confidence) / 2))
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return Interval(max(0.0, centre - half), min(1.0, centre + half), "Wilson")


def clopper_pearson(k: int, n: int, confidence: float = CONFIDENCE) -> Interval:
    a = (1 - confidence) / 2
    lo = 0.0 if k == 0 else float(beta.ppf(a, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - a, k + 1, n - k))
    return Interval(lo, hi, "Clopper-Pearson")


def interval(k: int, n: int, confidence: float = CONFIDENCE) -> Interval:
    """The interval the contract asks for: Clopper-Pearson at 0 or n, else Wilson."""
    if n <= 0:
        raise ValueError("no evaluated bases: the rate is undefined")
    if not 0 <= k <= n:
        raise ValueError(f"violations {k} not in 0..{n}")
    return clopper_pearson(k, n, confidence) if k in (0, n) else wilson(k, n, confidence)


@dataclass
class MRResult:
    """Everything the headline table needs for one MR (Testing.md 8)."""

    mr: str
    family: str
    seeds: tuple[int, ...]
    n_bases: int  # bases drawn for this MR
    violations: int  # violating bases (any-seed rule in Mode B)
    skipped: dict[str, int] = field(default_factory=dict)  # reason -> bases
    pairs: int | None = None  # Mode B: evaluated (base, seed) pairs
    pair_violations: int | None = None
    unconditioned: tuple[int, int] | None = None  # (violations, evaluated) without report-field skips

    @property
    def n_skipped(self) -> int:
        return sum(self.skipped.values())

    @property
    def evaluated(self) -> int:
        return self.n_bases - self.n_skipped


def _pct(x: float) -> str:
    return f"{x * 100:.1f} %"


def _rate(k: int, n: int) -> str:
    if n == 0:
        return "n/a (0 evaluated)"
    ci = interval(k, n)
    return f"{k}/{n} = {_pct(k / n)} [{_pct(ci.lo)}, {_pct(ci.hi)}] {ci.method}"


def headline_table(results: list[MRResult], title: str = "Headline results") -> str:
    head = ["MR", "Family", "Seeds", "Bases", "Evaluated", "Skipped (by reason)",
            "Violation rate, 95 % CI", "Per-pair rate (Mode B)", "Unconditioned"]
    lines = [f"# {title}", "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in results:
        skipped = "; ".join(f"{reason}: {n}" for reason, n in sorted(r.skipped.items())) or "none"
        pair = _rate(r.pair_violations, r.pairs) if r.pairs is not None and r.pair_violations is not None else "-"
        uncond = (_rate(*r.unconditioned) if r.mr.removeprefix("MR") in UNCONDITIONED_MRS
                  and r.unconditioned else "-")
        row = [r.mr, r.family, ", ".join(map(str, r.seeds)), str(r.n_bases), str(r.evaluated),
               f"{r.n_skipped} ({skipped})", _rate(r.violations, r.evaluated), pair, uncond]
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "A skip is not a pass. A reason joined with `+` means every one of those applied to the base. "
                  "Wilson score interval, or Clopper-Pearson when the "
                  "violation count is 0 or n (contracts/Testing.md 8)."]
    return "\n".join(lines) + "\n"


def write_headline_table(results: list[MRResult], path: str | Path = "results/headline_table.md", **kw) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(headline_table(results, **kw), encoding="utf-8")
    return p
