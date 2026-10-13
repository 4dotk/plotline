"""Seeded base-input generator (contracts/Testing.md section 4, T25).

One base input = one distinct ``Criteria`` (canonical JSON). Every draw and
every per-MR parameter comes from one ``numpy`` stream seeded by ``GEN_SEED``,
so the base list and all parameters regenerate exactly. Eligibility is decided
on the unmodified snapshot:

* broad stratum: >= 60 matching rows;
* thin stratum:  20-59 matching rows and a price band (these exercise L2).

Target mix 80 % broad, 20 % thin. The generator sets no ``sqft_range`` and no
``sale_cond`` (a stated threat to validity).

Run ``python -m tests.mt.generator [n]`` to write ``results/bases_and_params.json``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from plotline.contract import (
    CANONICAL_LOCALITIES,
    GEN_SEED,
    WINDOW_MONTHS,
    Criteria,
    canonical_criteria_json,
    month_add,
    window_months,
)
from tests.mt.oracle import matching_rows

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "data" / "chennai_snapshot.csv"
BASES_FILE = ROOT / "results" / "bases_and_params.json"

# Testing.md 4 (generator rules; not section 3 constants)
MIN_LOCALITY_SALES = 30
MIN_BHK_SALES = 10
BROAD_MIN_ROWS = 60
THIN_ROWS = (20, 59)
THIN_SHARE = 0.2
Q_LO = (0.0, 0.4)
Q_HI = (0.6, 1.0)
# Testing.md 5.1 per-MR parameter choices
MR4_X = (250_000, 1_000_000)
MR5_DELTA = (0.1, 0.3)
MR8_K = (2, 4, 10)
MAX_DRAWS_PER_BASE = 200


@dataclass
class Base:
    base_id: int
    stratum: str  # "broad" or "thin"
    n_rows: int  # matching rows on the unmodified snapshot
    criteria: dict  # Criteria fields
    canonical: str  # canonical JSON (the identity of the base)
    params: dict = field(default_factory=dict)  # per-MR parameters

    def to_criteria(self) -> Criteria:
        return Criteria.model_validate(self.criteria)


def valid_window_ends(df: pd.DataFrame) -> list[str]:
    """Every ``window_end`` with a full window inside the data (4.4), read from the data."""
    months = df["sale_date"].astype(str).str.slice(0, 7)
    first, last = months.min(), months.max()
    ends, m = [], month_add(first, WINDOW_MONTHS - 1)
    while m <= last:
        ends.append(m)
        m = month_add(m, 1)
    return ends


def _draw_criteria(rng: np.random.Generator, df: pd.DataFrame, ends: list[str]) -> dict | None:
    window_end = ends[rng.integers(len(ends))]  # uniform; never the default (D2)
    in_window = df[df["sale_date"].astype(str).str.slice(0, 7).isin(window_months(window_end))]

    by_loc = in_window["locality"].value_counts()
    eligible = sorted(loc for loc in CANONICAL_LOCALITIES if by_loc.get(loc, 0) >= MIN_LOCALITY_SALES)
    if not eligible:
        return None
    size = int(rng.integers(1, len(eligible) + 1))
    localities = sorted(rng.choice(eligible, size=size, replace=False).tolist())
    pool = in_window[in_window["locality"].isin(localities)]

    bhk = None
    if rng.random() >= 0.5:
        by_bhk = pool["bhk"].value_counts()
        ok = sorted(int(b) for b, n in by_bhk.items() if n >= MIN_BHK_SALES)
        if ok:
            k = int(rng.integers(1, min(2, len(ok)) + 1))
            bhk = sorted(int(b) for b in rng.choice(ok, size=k, replace=False))
            pool = pool[pool["bhk"].isin(bhk)]

    price_band = None
    if rng.random() >= 0.5 and len(pool):
        q_lo, q_hi = rng.uniform(*Q_LO), rng.uniform(*Q_HI)
        prices = pool["price"].to_numpy()
        # observed prices at the drawn quantiles, so the band is written as the data is
        price_band = [int(np.quantile(prices, q_lo, method="lower")), int(np.quantile(prices, q_hi, method="higher"))]

    return dict(localities=localities, window_end=window_end, bhk=bhk, price_band=price_band,
                sqft_range=None, sale_cond=None, price_unit="inr")


def _draw_params(rng: np.random.Generator, criteria: dict) -> dict:
    """Per-MR parameters, drawn in a fixed order from the same stream."""
    months = window_months(criteria["window_end"])
    locs = criteria["localities"] or list(CANONICAL_LOCALITIES)
    subset = None
    if len(locs) >= 2:  # MR6 needs a proper non-empty subset
        k = int(rng.integers(1, len(locs)))
        subset = sorted(rng.choice(locs, size=k, replace=False).tolist())
    return {
        "MR1": {"permutation_seed": int(rng.integers(2**31))},
        "MR4": {"X": int(rng.choice(MR4_X)), "month": months[int(rng.integers(len(months)))]},
        "MR5": {"delta": float(rng.choice(MR5_DELTA))},
        "MR6": {"subset": subset},
        "MR8": {"k": int(rng.choice(MR8_K))},
    }


def generate(df: pd.DataFrame, n: int, seed: int = GEN_SEED, ends: list[str] | None = None) -> list[Base]:
    """``n`` distinct bases, about ``THIN_SHARE`` of them thin, in generator order.
    ``ends`` restricts ``window_end`` (MR9 reserves bases at the latest month, Testing.md 7)."""
    rng = np.random.default_rng(seed)
    ends = ends or valid_window_ends(df)
    n_thin = round(n * THIN_SHARE)
    quota = {"thin": n_thin, "broad": n - n_thin}
    bases: list[Base] = []
    seen: set[str] = set()
    draws = 0
    while len(bases) < n:
        draws += 1
        if draws > MAX_DRAWS_PER_BASE * n:
            raise RuntimeError(f"generator stalled after {draws} draws with {len(bases)} of {n} bases")
        crit = _draw_criteria(rng, df, ends)
        if crit is None:
            continue
        n_rows = len(matching_rows(df, crit))
        if n_rows >= BROAD_MIN_ROWS:
            stratum = "broad"
        elif THIN_ROWS[0] <= n_rows <= THIN_ROWS[1] and crit["price_band"] is not None:
            stratum = "thin"
        else:
            continue
        canonical = canonical_criteria_json(Criteria.model_validate(crit))
        if quota[stratum] == 0 or canonical in seen:
            continue
        quota[stratum] -= 1
        seen.add(canonical)
        bases.append(Base(len(bases), stratum, n_rows, crit, canonical, _draw_params(rng, crit)))
    return bases


def save_bases(bases: list[Base], path: str | Path = BASES_FILE, seed: int = GEN_SEED,
               snapshot_sha256: str | None = None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "gen_seed": seed,
        "snapshot_sha256": snapshot_sha256,
        "n_bases": len(bases),
        "strata": {s: sum(b.stratum == s for b in bases) for s in ("broad", "thin")},
        "bases": [asdict(b) for b in bases],
    }
    p.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return p


def load_bases(path: str | Path = BASES_FILE) -> list[Base]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Base(**b) for b in doc["bases"]]


def main(argv: list[str]) -> int:
    n = int(argv[0]) if argv else 100
    df = pd.read_csv(SNAPSHOT)
    sha = (ROOT / "data" / "SNAPSHOT.sha256").read_text().split()[0]
    bases = generate(df, n)
    path = save_bases(bases, snapshot_sha256=sha)
    thin = sum(b.stratum == "thin" for b in bases)
    print(f"{len(bases)} bases ({len(bases) - thin} broad, {thin} thin), GEN_SEED={GEN_SEED} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
