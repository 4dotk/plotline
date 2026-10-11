"""Write the UI example files into examples/ from the real frozen snapshot.

    python scripts/make_example_responses.py

The numbers are computed here, straight from data/chennai_snapshot.csv, with
the formulas of GLOBAL_CONTRACT.md 6.2/6.3 (the same ones as
scripts/golden_vectors.py). They do not come from the agents, so the files stay
correct while the agents are still stubs. Every report is built through
``build_report`` and so validated by ``TrendReport``.

Files:
  example_response.json         ok report: all 7 localities, window ending 2015-02
                                (golden A1: two price_jump flags, a template diagnostic each)
  example_response_loops.json   ok report where L1 (1 repair) and L2 (2 widenings) fire
                                (golden A3 with an inverted price band added)
  example_response_error.json   error report (E_INVALID_CRITERIA)
  example_meta.json             what GET /api/meta returns
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from plotline.agents.reporter import build_report  # noqa: E402
from plotline.api import build_meta  # noqa: E402
from plotline.contract import (  # noqa: E402
    ALL_REGION, ANOMALY_PCT, CANONICAL_LOCALITIES, COUNT_DROP, COVERAGE_MIN_MONTHS, FLAT_BAND_PCT,
    L2_WIDEN, MIN_BUCKET_N, AnomalyFlag, Criteria, Diagnostic, ErrorInfo, LoopCounters, StatChange,
    Summary, TrendRecord, report_to_json, window_months,
)
from plotline.trace import TraceLog, l2_action_text  # noqa: E402

OUT = ROOT / "examples"
SHA = (ROOT / "data" / "SNAPSHOT.sha256").read_text().split()[0]
LOGIC = "abc1234"  # fixed so the examples do not change with every commit


# ---------------------------------------------------------------- computation


def matching_rows(df: pd.DataFrame, c: Criteria) -> pd.DataFrame:
    months = window_months(c.window_end)
    d = df[df["sale_date"].str[:7].isin(months)].copy()
    d["month"] = d["sale_date"].str[:7]
    if c.localities is not None:
        d = d[d["locality"].isin(c.localities)]
    if c.bhk is not None:
        d = d[d["bhk"].isin(c.bhk)]
    if c.price_band is not None:
        d = d[(d["price"] >= c.price_band[0]) & (d["price"] <= c.price_band[1])]
    if c.sqft_range is not None:
        d = d[(d["sqft"] >= c.sqft_range[0]) & (d["sqft"] <= c.sqft_range[1])]
    if c.sale_cond is not None:
        d = d[d["sale_cond"].isin(c.sale_cond)]
    d["ppsf"] = d["price"].astype("float64") / d["sqft"].astype("float64")
    return d


def bucket(g: pd.DataFrame) -> tuple[int, int, float | None, float | None]:
    n = len(g)
    ok = g[(g["price"] > 0) & (g["sqft"] > 0)]
    if len(ok) == 0:
        return n, 0, None, None
    return n, len(ok), float(np.median(ok["price"])), float(np.median(ok["ppsf"]))


def coverage_months(d: pd.DataFrame, c: Criteria) -> int:
    return sum(bucket(d[d["month"] == m])[1] >= MIN_BUCKET_N for m in window_months(c.window_end))


def compute(df: pd.DataFrame, c: Criteria):
    d = matching_rows(df, c)
    months = window_months(c.window_end)
    regions = [ALL_REGION] + sorted(c.localities if c.localities is not None else CANONICAL_LOCALITIES)
    recs: list[TrendRecord] = []
    for m in months:
        for r in regions:
            g = d[d["month"] == m] if r == ALL_REGION else d[(d["month"] == m) & (d["locality"] == r)]
            n, nb, mp, mpp = bucket(g)
            recs.append(TrendRecord(month=m, region_key=r, listing_count=n, n_in_bucket=nb,
                                    median_price=mp, median_price_per_sqft=mpp, low_sample=nb < MIN_BUCKET_N,
                                    pct_change_price_per_sqft=None))
    allr = {r.month: r for r in recs if r.region_key == ALL_REGION}
    flags: list[AnomalyFlag] = []
    for prev_m, m in zip(months, months[1:]):
        p, cur = allr[prev_m], allr[m]
        if p.n_in_bucket >= MIN_BUCKET_N and cur.n_in_bucket >= MIN_BUCKET_N:
            pct = cur.median_price_per_sqft / p.median_price_per_sqft - 1
            cur.pct_change_price_per_sqft = float(pct)
            if abs(pct) > ANOMALY_PCT:
                verb = "rose" if pct > 0 else "fell"
                flags.append(AnomalyFlag(month=m, region_key="ALL", kind="price_jump", value=float(pct),
                                         threshold=ANOMALY_PCT,
                                         reason=f"median price per sqft {verb} {abs(pct) * 100:.1f}% vs {prev_m}"))
        if p.n_in_bucket >= MIN_BUCKET_N and cur.listing_count <= COUNT_DROP * p.listing_count:
            ratio = cur.listing_count / p.listing_count
            flags.append(AnomalyFlag(month=m, region_key="ALL", kind="count_drop", value=float(ratio),
                                     threshold=COUNT_DROP,
                                     reason=f"listings fell to {ratio * 100:.0f}% of {prev_m} "
                                            f"({cur.listing_count} vs {p.listing_count})"))

    def stat(sub: pd.DataFrame, col: str) -> float:
        return float(np.median(sub[col]))

    first, last = d[d["month"].isin(months[:3])], d[d["month"].isin(months[-3:])]
    if len(first) >= MIN_BUCKET_N and len(last) >= MIN_BUCKET_N:
        def sc(col):
            s, e = stat(first, col), stat(last, col)
            ch = (e / s - 1) * 100
            return StatChange(start=s, end=e, change_pct=ch,
                              direction="up" if ch > FLAT_BAND_PCT else "down" if ch < -FLAT_BAND_PCT else "flat")
        summary = Summary(n_rows=len(d), price=sc("price"), price_per_sqft=sc("ppsf"))
    else:
        summary = Summary(n_rows=len(d), price=None, price_per_sqft=None)
    cov = coverage_months(d, c)
    return recs, summary, flags, cov, len(d)


# --------------------------------------------------------------------- reports


def write(name: str, report) -> None:
    OUT.mkdir(exist_ok=True)
    text = report_to_json(report)
    (OUT / name).write_text(json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote examples/{name}: status={report.status} records={len(report.records)} "
          f"flags={len(report.anomaly_flags)} trace={len(report.trace)}")


def common(**kw):
    base = dict(seed=0, llm_mode="off", logic_version=LOGIC, snapshot_sha256=SHA, loops_enabled=True, llm=None)
    base.update(kw)
    return base


def example_ok(df):
    c_in = Criteria(window_end="2015-02")
    c = c_in.model_copy(deep=True)
    recs, summary, flags, cov, n = compute(df, c)
    t = TraceLog()
    t.decision("planner", "topology=parallel (7 localities >= 3)")
    t.step("scanner", f"7 scanner(s), parallel: {n} rows")
    t.step("aggregator", f"{len(recs)} buckets (12 months x 8 regions)")
    t.step("validator", f"coverage {cov}/12 meets {COVERAGE_MIN_MONTHS}/12; no widening needed")
    t.step("anomaly", f"{len(flags)} anomaly flag(s) on the ALL series")
    t.step("diagnostic", f"template text for {len(flags)} flag(s) (LLM_MODE=off)")
    t.step("reporter", "report assembled")
    diags = [Diagnostic(month=f.month, text=f.reason, source="template") for f in flags]
    return build_report(error=None, criteria_in=c_in, effective=c, records=recs, summary=summary,
                        coverage_score=cov / 12, flags=flags, diagnostics=diags, trace=t.events,
                        loop_counters=t.loop_counters(), topology="parallel", n_scanners=7,
                        partial_last_month=True, **common())


def example_loops(df):
    """Golden A3 (Adyar, 1 BHK, 70-90 lakh, 2010-12) with the band typed the wrong way round."""
    c_in = Criteria(localities=["Adyar"], bhk=[1], price_band=[9_000_000, 7_000_000], window_end="2010-12")
    c = c_in.model_copy(deep=True)
    t = TraceLog()
    t.decision("planner", "topology=consolidated (1 locality < 3)")
    t.step("scanner", "1 scanner(s), consolidated: scan on the criteria as received")
    t.warning("aggregator", "invalid price_band: band_inverted; asking the planner to repair (L1)")
    c.price_band = [7_000_000, 9_000_000]
    t.l1_fired("band_inverted", [9_000_000, 7_000_000], [7_000_000, 9_000_000], 1)
    d = matching_rows(df, c)
    t.step("scanner", f"1 scanner(s), consolidated: {len(d)} rows")
    t.step("aggregator", "24 buckets (12 months x ALL + Adyar)")
    lo, hi = c.price_band
    width = hi - lo
    for attempt, factor in enumerate(L2_WIDEN, start=1):
        d = matching_rows(df, c)
        cov = coverage_months(d, c)
        t.step("validator", f"coverage {cov}/12 on {len(d)} rows")
        if cov >= COVERAGE_MIN_MONTHS:
            break
        if factor == "drop":
            c.price_band, band = None, None
        else:
            c.price_band = [round(lo - factor * width), round(hi + factor * width)]
            band = c.price_band
        t.l2_fired(cov, attempt, band, decided_by="rule")
        d = matching_rows(df, c)
        t.step("scanner", f"1 scanner(s), consolidated: {len(d)} rows after widening")
    recs, summary, flags, cov, n = compute(df, c)
    t.step("validator", f"coverage {cov}/12 meets {COVERAGE_MIN_MONTHS}/12; stop")
    t.step("anomaly", f"{len(flags)} anomaly flag(s) on the ALL series")
    t.step("diagnostic", f"template text for {len(flags)} flag(s) (LLM_MODE=off)")
    t.step("reporter", "report assembled")
    diags = [Diagnostic(month=f.month, text=f.reason, source="template") for f in flags]
    return build_report(error=None, criteria_in=c_in, effective=c, records=recs, summary=summary,
                        coverage_score=cov / 12, flags=flags, diagnostics=diags, trace=t.events,
                        loop_counters=t.loop_counters(), topology="consolidated", n_scanners=1,
                        partial_last_month=False, **common())


def example_error():
    c_in = Criteria(localities=["Velacheri-X"], window_end="2015-02")
    t = TraceLog()
    t.decision("planner", "topology=consolidated (1 locality < 3)")
    t.step("scanner", "1 scanner(s), consolidated: 0 rows")
    t.warning("aggregator", "invalid localities: locality_unknown; asking the planner to repair (L1)")
    err = ErrorInfo(code="E_INVALID_CRITERIA", message="invalid localities: no close match")
    t.error("planner", f"{err.code}: {err.message}", code=err.code)
    return build_report(error=err, criteria_in=c_in, effective=c_in, records=[], summary=None, coverage_score=0,
                        flags=[], diagnostics=[], trace=t.events, loop_counters=LoopCounters(L1_repairs=0, L2_attempts=0),
                        topology="consolidated", n_scanners=1, partial_last_month=False, **common())


def main() -> None:
    df = pd.read_csv(ROOT / "data" / "chennai_snapshot.csv")
    ok = example_ok(df)
    write("example_response.json", ok)
    write("example_response_loops.json", example_loops(df))
    write("example_response_error.json", example_error())
    (OUT / "example_meta.json").write_text(
        json.dumps(build_meta(df, SHA), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote examples/example_meta.json")

    # self-check against the golden numbers of golden.md A1
    allr = {r.month: r for r in ok.records if r.region_key == "ALL"}
    assert allr["2014-03"].listing_count == 24 and allr["2014-03"].median_price == 12440755.0
    assert abs(allr["2014-12"].pct_change_price_per_sqft - 0.148034813) < 1e-8
    assert [(f.month, f.kind) for f in ok.anomaly_flags] == [("2014-12", "price_jump"), ("2015-01", "price_jump")]
    assert ok.summary.n_rows == 338 and abs(ok.summary.price.change_pct - (-5.566902888)) < 1e-6
    print("golden A1 self-check passed")


if __name__ == "__main__":
    main()
