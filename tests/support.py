"""Shared test fixtures. Sample objects are written from CONTRACT.md / golden.md."""

from __future__ import annotations

import pandas as pd

from plotline.contract import (
    CANONICAL_LOCALITIES,
    LoopCounters,
    TrendReport,
    window_months,
)

SNAPSHOT_SHA = "18487b6ff164507f254c7bca38f13be786523b1e3fec03dd457bffa866cb6209"


def small_df() -> pd.DataFrame:
    """Tiny frame with the 7 snapshot columns spanning 2014-01 .. 2015-02, so the
    valid window ends (first month + 11 .. latest month) are 2014-12 .. 2015-02."""
    return pd.DataFrame(
        {
            "listing_id": ["P1", "P2", "P3"],
            "locality": ["Adyar", "Anna Nagar", "T Nagar"],
            "sqft": [1000, 1200, 900],
            "sale_date": ["2014-01-05", "2014-12-10", "2015-02-10"],
            "bhk": [1, 2, 2],
            "sale_cond": ["Normal Sale", "Family", "Partial"],
            "price": [5000000, 7000000, 6500000],
        }
    )


# golden.md A1: window_end 2015-02, ALL region
A1 = [
    ("2014-03", 24, 12440755.0, 8070.312067, None),
    ("2014-04", 22, 12020615.0, 8630.727643, 0.06944162409),
    ("2014-05", 34, 12308475.0, 8650.144189, 0.002249699676),
    ("2014-06", 31, 11216030.0, 8628.894737, -0.002456543058),
    ("2014-07", 31, 12026900.0, 8656.234991, 0.00316845383),
    ("2014-08", 28, 12691755.0, 9480.940645, 0.09527302047),
    ("2014-09", 25, 12368280.0, 8885.390295, -0.06281553402),
    ("2014-10", 25, 10676410.0, 9095.651659, 0.02366371723),
    ("2014-11", 35, 12123360.0, 9110.533333, 0.001636130662),
    ("2014-12", 32, 11722730.0, 10459.20943, 0.148034813),
    ("2015-01", 28, 11950775.0, 8919.117162, -0.1472474836),
    ("2015-02", 23, 11412420.0, 8508.576779, -0.04602926223),
]


def a1_report_dict() -> dict:
    """The golden.md A1 report (all 7 localities). The four localities without
    sales are zero buckets; the three active ones are also left empty because
    golden.md gives only their totals (the schema does not tie them to ALL)."""
    records = []
    for month, n, mp, mpps, pct in A1:
        records.append(
            dict(month=month, region_key="ALL", listing_count=n, n_in_bucket=n, median_price=mp,
                 median_price_per_sqft=mpps, low_sample=False, pct_change_price_per_sqft=pct)
        )
        for loc in CANONICAL_LOCALITIES:
            records.append(
                dict(month=month, region_key=loc, listing_count=0, n_in_bucket=0, median_price=None,
                     median_price_per_sqft=None, low_sample=True, pct_change_price_per_sqft=None)
            )
    crit = dict(localities=None, window_end="2015-02", bhk=None, price_band=None,
                sqft_range=None, sale_cond=None, price_unit="inr")
    return dict(
        status="ok", error=None, criteria_in=crit, effective_criteria=dict(crit), price_unit="inr",
        records=records,
        summary=dict(
            n_rows=338,
            price=dict(start=12303430.0, end=11618510.0, change_pct=-5.566902888, direction="down"),
            price_per_sqft=dict(start=8491.884579, end=8945.0, change_pct=5.335864105, direction="up"),
        ),
        coverage_score=1.0,
        anomaly_flags=[
            dict(month="2014-12", region_key="ALL", kind="price_jump", value=0.148034813,
                 threshold=0.12, reason="median price per sqft rose 14.8% vs 2014-11"),
            dict(month="2015-01", region_key="ALL", kind="price_jump", value=-0.1472474836,
                 threshold=0.12, reason="median price per sqft fell 14.7% vs 2014-12"),
        ],
        diagnostics=[
            dict(month="2014-12", text="template text", source="template"),
            dict(month="2015-01", text="template text", source="template"),
        ],
        trace=[dict(i=0, agent="planner", kind="decision", loop=None,
                    msg="topology=parallel (7 localities >= 3)", data={})],
        metadata=dict(contract_version="1.1.1", logic_version="abc1234", snapshot_sha256=SNAPSHOT_SHA,
                      seed=0, llm_mode="off", topology="parallel", n_scanners=7, loops_enabled=True,
                      loop_counters=dict(L1_repairs=0, L2_attempts=0), partial_last_month=True, llm=None),
    )


def a1_report() -> TrendReport:
    return TrendReport.model_validate(a1_report_dict())


class FakeChat:
    """Stand-in for the live model: returns scripted answers in order and records calls."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, str, int]] = []

    def __call__(self, system: str, user: str, seed: int, schema: dict) -> str:
        self.calls.append((system, user, seed))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def llm_config(mode: str = "live", cache_path=None, **kw):
    """A complete live/replay configuration for tests (never reaches a server)."""
    from pathlib import Path

    from plotline.llm_client import LlmConfig

    values = dict(
        mode=mode, model_tag="test-model-q4", base_url="http://127.0.0.1:1/v1", model="server-name",
        cache_path=Path(cache_path) if cache_path else Path("/nonexistent/llm_replay.jsonl"),
        backend="llama serve", build="b0000", launch_flags="--ctx 4096", gguf_sha256="a" * 64,
        quant="Q4_K_M", ctx=4096,
    )
    values.update(kw)
    return LlmConfig(**values)
