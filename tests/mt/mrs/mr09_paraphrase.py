"""MR9, paraphrase the sentence (contracts/Testing.md 5, 7).

Family: invariance. Source: the base's canonical sentence. Follow-ups: the other
phrasings (≥ 4), each its own pair; a base violates if any phrasing violates.
Phrasings come from the committed templates below, not from the LLM, so they
regenerate from ``GEN_SEED`` (Testing.md 12 #10). Bases at the latest month get
"last year" / "past 12 months" wordings in place of two dated ones.
Assert: **first** ``effective_criteria`` EXACT (set semantics); only if equal,
``records``, ``summary``, ``anomaly_flags`` and ``coverage_score`` EXACT.
Not asserted: ``diagnostics``, ``trace``.
Skip: ``LLM_MODE = off`` (``metadata.llm_mode``, any run).
Targeted fault: the Planner (LLM) not mapping paraphrases to the same criteria.

``python -m tests.mt.mrs.mr09_paraphrase`` writes the Mode B query file
``tests/mt/queries/mr9_paraphrases.json`` (``MODE_B_BASES`` bases, of which
``LATEST_SHARE`` at the latest month).
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd

from plotline.contract import GEN_SEED, Criteria, canonical_criteria_json
from tests.mt.generator import ROOT, SNAPSHOT, Base, generate, valid_window_ends
from tests.mt.harness import MR, Diff, FollowUp, diff, exact, keyed

QUERIES_FILE = ROOT / "tests" / "mt" / "queries" / "mr9_paraphrases.json"
MODE_B_BASES = 50  # Testing.md 4: >= 30, 50 target
LATEST_SHARE = 0.2  # share of Mode B bases reserved at window_end = latest month (Testing.md 7)
INR_PER_LAKH = 100_000  # contract 5.2
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December")
COMPARED = ("records", "summary", "anomaly_flags", "coverage_score")


# ---------------------------------------------------------------------------
# Phrasing templates
# ---------------------------------------------------------------------------


def _lakh(inr: float) -> str:
    """INR as an exact decimal number of lakh: 7738700 -> "77.387"."""
    text = f"{inr / INR_PER_LAKH:.5f}".rstrip("0").rstrip(".")
    return text or "0"


def _join(items: list[str], word: str) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" {word} " + items[-1]


def _parts(c: dict) -> dict:
    locs = c["localities"]
    y, m = c["window_end"].split("-")
    name = MONTH_NAMES[int(m) - 1]
    bhk = c["bhk"]
    band = c["price_band"]
    lo, hi = (_lakh(band[0]), _lakh(band[1])) if band else (None, None)
    return {
        "locs": _join(locs, "and"),
        "locs_rev": _join(list(reversed(locs)), "or"),
        "month": f"{name} {y}", "mon": f"{name[:3]} {y}", "iso": c["window_end"],
        "bhk_or": f"{_join([str(b) for b in bhk], 'or')} BHK " if bhk else "",
        "bhk_bed": f"{_join([str(b) for b in bhk], 'and')} bedroom " if bhk else "",
        "band_between": f" priced between {lo} lakh and {hi} lakh" if band else "",
        "band_to": f" in the {lo} to {hi} lakh range" if band else "",
        "band_dash": f", {lo}-{hi} lakh" if band else "",
    }


DATED = (  # canonical first
    "Median prices of {bhk_or}homes in {locs}{band_between} for the 12 months ending {month}",
    "How did {bhk_bed}flat prices in {locs_rev}{band_to} move in the year to {iso}?",
    "Show the 12-month housing price trend for {locs}{band_dash}, {bhk_or}window ending {mon}",
    "{locs_rev}: {bhk_bed}property sale prices{band_between}, twelve months up to {month}",
    "Price trend of {bhk_or}apartments sold in {locs}{band_to} during the year ending {iso}",
)
LATEST = (  # replace the last two dated phrasings when window_end is the latest month
    "How have {bhk_or}home prices in {locs}{band_between} changed over the last year?",
    "{bhk_bed}flat prices in {locs_rev}{band_to} in the past 12 months",
)


def phrasings(criteria: dict, latest_month: str | None = None) -> list[str]:
    """The canonical sentence, then the paraphrases (>= 4)."""
    templates = DATED if criteria["window_end"] != latest_month else DATED[:-2] + LATEST
    parts = _parts(criteria)
    return [" ".join(t.format(**parts).split()) for t in templates]


# ---------------------------------------------------------------------------
# The MR
# ---------------------------------------------------------------------------


def _latest(df: pd.DataFrame) -> str:
    return valid_window_ends(df)[-1]


def source(base: Base) -> str:
    return base.params["MR9"]["phrasings"][0]


def transform(base: Base, df: pd.DataFrame) -> list[FollowUp]:
    return [FollowUp(p, df.copy()) for p in base.params["MR9"]["phrasings"][1:]]


def with_phrasings(bases: list[Base], df: pd.DataFrame) -> list[Base]:
    """The bases with ``params["MR9"]`` filled in (deterministic from the criteria)."""
    latest = _latest(df)
    return [replace(b, params={**b.params, "MR9": {"phrasings": phrasings(b.criteria, latest)}}) for b in bases]


def _canon(eff: dict | None) -> str | None:
    return None if eff is None else canonical_criteria_json(Criteria.model_validate(eff))


def check(src: dict, fus: list[dict], base: Base) -> list[Diff]:
    out: list[Diff] = []
    for i, fu in enumerate(fus, start=1):
        p = f"phrasing[{i}]"
        a, b = _canon(src["effective_criteria"]), _canon(fu["effective_criteria"])
        if a != b:
            out.append(Diff(f"{p}.effective_criteria", a, b))
            continue
        ka, kb = keyed(src), keyed(fu)
        for f in COMPARED:
            out += diff(ka[f], kb[f], exact, f"{p}.{f}")
    return out


def llm_off(report: dict) -> str | None:
    return "LLM_MODE = off" if report["metadata"]["llm_mode"] == "off" else None


def skip(src: dict, fus: list[dict], base: Base) -> str | None:
    return next((r for r in map(llm_off, (src, *fus)) if r is not None), None)


def precondition(base: Base, df: pd.DataFrame) -> str | None:
    return None if "MR9" in base.params else "no phrasings (bases not passed through with_phrasings)"


MR9 = MR(name="MR9", family="invariance", transform=transform, check=check, skip=skip,
         precondition=precondition, source=source, source_skip=llm_off)


# ---------------------------------------------------------------------------
# Mode B query file
# ---------------------------------------------------------------------------


def mode_b_bases(df: pd.DataFrame, n: int = MODE_B_BASES, seed: int = GEN_SEED) -> list[Base]:
    """``n`` bases, ``LATEST_SHARE`` of them at the latest month, with phrasings; ids 0..n-1."""
    n_latest = round(n * LATEST_SHARE)
    dated = generate(df, n - n_latest, seed)
    seen = {b.canonical for b in dated}
    pool = generate(df, 2 * n_latest, seed, ends=[_latest(df)])  # over-draw: a dated base may be at the latest month
    latest = [b for b in pool if b.canonical not in seen][:n_latest]
    merged = [replace(b, base_id=i) for i, b in enumerate(dated + latest)]
    return with_phrasings(merged, df)


def save_queries(bases: list[Base], path: Path = QUERIES_FILE, seed: int = GEN_SEED) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "gen_seed": seed, "n_bases": len(bases),
        "n_last_year": sum(any("last year" in p for p in b.params["MR9"]["phrasings"]) for b in bases),
        "queries": [{"base_id": b.base_id, "stratum": b.stratum, "criteria": b.criteria,
                     "canonical": b.params["MR9"]["phrasings"][0],
                     "paraphrases": b.params["MR9"]["phrasings"][1:]} for b in bases],
    }
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main(argv: list[str]) -> int:
    df = pd.read_csv(SNAPSHOT)
    bases = mode_b_bases(df, int(argv[0]) if argv else MODE_B_BASES)
    path = save_queries(bases)
    print(f"{len(bases)} bases, {sum(len(b.params['MR9']['phrasings']) for b in bases)} sentences -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
