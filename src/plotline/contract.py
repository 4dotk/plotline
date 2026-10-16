"""Constants and runtime schemas for the Chennai housing-trends application.

CONTRACT.md is the single source of truth. This module only *implements* it:
there is no second contract here. If this file and CONTRACT.md disagree, this
file is the defect. Agents import their types from here (see the agent shards).

Contents
  * Section 3 constants (the only place these numbers may appear).
  * Filter  : ``Criteria``, ``RunOptions``      (5.2, 5.3)
  * Report  : ``TrendRecord``, ``Summary``, ``StatChange``, ``AnomalyFlag``,
              ``ErrorInfo``, ``Diagnostic``, ``Metadata``, ``LoopCounters``,
              ``TrendReport``                      (6.2 to 6.5)
  * Trace   : ``TraceEvent``                   (7.4)

Validation is of two kinds:
  * shape: types, enums, formats (every model);
  * consistency: relations that CONTRACT.md states in words or formulas
    (6.2, 6.3, 7.2, 7.4), for example "low_sample == n_in_bucket < MIN_BUCKET_N".
    ``TrendReport`` checks these across its parts.

``Criteria`` checks shape only. A request with an unknown locality, an inverted
band or an out-of-range value is a *valid shape* that the L1 loop repairs; it
becomes invalid only when it appears in an ``ok`` report's ``effective_criteria``.
"""

from __future__ import annotations

import json
import math
import re
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# Section 3: constants. No other file may contain these numbers.
# ---------------------------------------------------------------------------

CONTRACT_VERSION = "1.2.0"

WINDOW_MONTHS = 12
DEFAULT_WINDOW_END = "latest"  # resolves to the snapshot's latest month (2015-02), D2
MIN_BUCKET_N = 5
COVERAGE_MIN_MONTHS = 9
ANOMALY_PCT = 0.12
COUNT_DROP = 0.5
FLAT_BAND_PCT = 1.0
L1_CAP = 2
L2_CAP = 3
L2_WIDEN = (0.20, 0.50, "drop")
TOPOLOGY_PARALLEL_MIN_LOCALITIES = 3
REL_TOL = 1e-9
ABS_TOL = 1e-9
ABS_TOL_PCT = 1e-7
SEEDS = (101, 202, 303)
GEN_SEED = 42

# ---------------------------------------------------------------------------
# Section 4.3 vocabularies (snapshot columns)
# ---------------------------------------------------------------------------

CANONICAL_LOCALITIES = (
    "Adyar",
    "Anna Nagar",
    "Chrompet",
    "KK Nagar",
    "Karapakkam",
    "T Nagar",
    "Velachery",
)
CANONICAL_SALE_CONDS = ("AbNormal", "AdjLand", "Family", "Normal Sale", "Partial")
BHK_VALUES = (1, 2, 3, 4)
ALL_REGION = "ALL"

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

PriceUnit = Literal["inr", "lakh"]  # 5.2, D6
Topology = Literal["parallel", "consolidated"]  # 7.1
Status = Literal["ok", "error"]  # 6.2
ErrorCode = Literal[  # 6.5
    "E_INVALID_CRITERIA",
    "E_NL_UNPARSEABLE",
    "E_LLM_OFF",
    "E_REPLAY_MISS",
    "E_SCHEMA",
    "E_SNAPSHOT_HASH",
]
LlmMode = Literal["live", "replay", "off"]  # 8
AnomalyKind = Literal["price_jump", "count_drop"]  # 6.3
Direction = Literal["up", "down", "flat"]  # 6.2
DiagnosticSource = Literal["llm", "template"]  # 6.2
TraceAgent = Literal[  # 7.4
    "planner", "inspector", "scanner", "aggregator", "validator", "anomaly", "diagnostic", "reporter"
]
NoticeKind = Literal[  # 6.2 (1.2.0): what the user must be told about how the question was answered
    "repaired",      # L1 changed the request (window clamped, band swapped, BHK dropped, place matched)
    "out_of_scope",  # the request asks for something the data does not hold; it could not be answered
    "no_sales",      # valid, but no sales match the hard filters (locality, window, BHK) somewhere
    "widened",       # L2 widened or dropped the soft filters
    "not_read",      # the sentence mentions a filter the criteria do not contain (parse audit)
]
TraceKind = Literal["step", "decision", "loop", "warning", "error"]  # 7.4
LoopName = Literal["L1", "L2"]  # 7.4

# ---------------------------------------------------------------------------
# Shared field types
# ---------------------------------------------------------------------------

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
Month = Annotated[StrictStr, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
Sha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[StrictInt, Field(ge=0)]
# A number "as written": an int stays an int, a float stays a float (5.2 canonical JSON).
Num = Union[StrictInt, Annotated[StrictFloat, Field(allow_inf_nan=False)]]
Real = Annotated[float, Field(allow_inf_nan=False)]
Range2 = Annotated[list[Num], Field(min_length=2, max_length=2)]


class _Model(BaseModel):
    """Strict base: unknown fields are errors, no type coercion."""

    model_config = ConfigDict(extra="forbid", strict=True)


# ---------------------------------------------------------------------------
# Month helpers (4.4): the window is the 12 months ending at window_end, inclusive.
# ---------------------------------------------------------------------------


def _month_index(m: str) -> int:
    return int(m[:4]) * 12 + int(m[5:7]) - 1


def _month_from_index(i: int) -> str:
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def month_add(month: str, k: int) -> str:
    """``month`` shifted by ``k`` calendar months (k may be negative)."""
    return _month_from_index(_month_index(month) + k)


def window_months(window_end: str) -> list[str]:
    """The 12 calendar months ``window_end - 11 .. window_end``, ascending."""
    end = _month_index(window_end)
    return [_month_from_index(i) for i in range(end - WINDOW_MONTHS + 1, end + 1)]


# ---------------------------------------------------------------------------
# Filter: Criteria (5.2)
# ---------------------------------------------------------------------------


class Criteria(_Model):
    """A request, or the criteria actually computed (shape check only)."""

    localities: list[StrictStr] | None = None  # null = all 7
    window_end: Month | None = None  # null = latest month (D2)
    bhk: list[StrictInt] | None = None  # null = any
    price_band: Range2 | None = None  # soft, inclusive, in price_unit
    sqft_range: Range2 | None = None  # soft, inclusive
    sale_cond: list[StrictStr] | None = None  # soft
    price_unit: PriceUnit = "inr"

    def domain_violations(self) -> list[str]:
        """Problems that make these criteria unfit for an ``ok`` report.

        Codes follow the L1 issue names of 7.3. ``window_out_of_range`` is not
        checked here because the valid range is read from the data (4.4).
        """
        issues: list[str] = []
        if self.price_band is not None and self.price_band[0] > self.price_band[1]:
            issues.append("band_inverted")
        if self.localities is not None and any(
            loc not in CANONICAL_LOCALITIES for loc in self.localities
        ):
            issues.append("locality_unknown")
        if self.bhk is not None and any(b not in BHK_VALUES for b in self.bhk):
            issues.append("bhk_out_of_range")
        if self.sale_cond is not None and any(
            s not in CANONICAL_SALE_CONDS for s in self.sale_cond
        ):
            issues.append("sale_cond_unknown")
        return issues


def canonical_json(obj: Any) -> str:
    """Keys sorted, no whitespace, shortest round-trip numbers, UTF-8."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def canonical_criteria_json(criteria: Criteria) -> str:
    """Canonical JSON of a ``Criteria`` for the "same base input" rule (5.2).

    List filters are compared as sets, so ``localities``, ``bhk`` and
    ``sale_cond`` are sorted and de-duplicated. Ranges are ordered pairs and
    are left as written.
    """
    d = criteria.model_dump(mode="json")
    for key in ("localities", "bhk", "sale_cond"):
        if d[key] is not None:
            d[key] = sorted(set(d[key]))
    return canonical_json(d)


# ---------------------------------------------------------------------------
# RunOptions (5.3): test hooks; defaults reproduce normal behaviour
# ---------------------------------------------------------------------------


class RunOptions(_Model):
    loops_enabled: StrictBool = True
    force_topology: Topology | None = None


# ---------------------------------------------------------------------------
# Report parts (6.2)
# ---------------------------------------------------------------------------


class TrendRecord(_Model):
    month: Month
    region_key: StrictStr  # "ALL" or a canonical locality
    listing_count: Count
    n_in_bucket: Count
    median_price: Real | None
    median_price_per_sqft: Real | None
    low_sample: StrictBool
    pct_change_price_per_sqft: Real | None  # ALL records only

    @field_validator("region_key")
    @classmethod
    def _region(cls, v: str) -> str:
        if v != ALL_REGION and v not in CANONICAL_LOCALITIES:
            raise ValueError(f"region_key must be 'ALL' or a canonical locality, got {v!r}")
        return v

    @model_validator(mode="after")
    def _check(self) -> "TrendRecord":
        if self.n_in_bucket > self.listing_count:
            raise ValueError("n_in_bucket must be <= listing_count")
        if self.low_sample != (self.n_in_bucket < MIN_BUCKET_N):
            raise ValueError("low_sample must equal n_in_bucket < MIN_BUCKET_N")
        empty = self.n_in_bucket == 0
        if empty != (self.median_price is None) or empty != (
            self.median_price_per_sqft is None
        ):
            raise ValueError("medians are null exactly when n_in_bucket == 0")
        if self.region_key != ALL_REGION and self.pct_change_price_per_sqft is not None:
            raise ValueError("pct_change_price_per_sqft is set on ALL records only")
        return self


class StatChange(_Model):
    """``summary.price`` / ``summary.price_per_sqft``: first 3 vs last 3 months."""

    start: Real
    end: Real
    change_pct: Real  # in percent
    direction: Direction

    @model_validator(mode="after")
    def _check(self) -> "StatChange":
        if self.change_pct > FLAT_BAND_PCT:
            expected = "up"
        elif self.change_pct < -FLAT_BAND_PCT:
            expected = "down"
        else:
            expected = "flat"
        if self.direction != expected:
            raise ValueError(f"direction must be {expected!r} for change_pct={self.change_pct}")
        return self


class Summary(_Model):
    n_rows: Count
    price: StatChange | None
    price_per_sqft: StatChange | None

    @model_validator(mode="after")
    def _check(self) -> "Summary":
        # Both are null when the pooled first-3 or last-3 set has < MIN_BUCKET_N rows.
        if (self.price is None) != (self.price_per_sqft is None):
            raise ValueError("price and price_per_sqft are null together")
        return self


class AnomalyFlag(_Model):
    month: Month
    region_key: Literal["ALL"]  # anomalies are detected on the ALL series (D5)
    kind: AnomalyKind
    value: Real
    threshold: Real
    reason: StrictStr

    @model_validator(mode="after")
    def _check(self) -> "AnomalyFlag":
        expected = ANOMALY_PCT if self.kind == "price_jump" else COUNT_DROP
        if self.threshold != expected:
            raise ValueError(f"threshold for {self.kind} must be {expected}")
        return self


class ErrorInfo(_Model):
    code: ErrorCode
    message: StrictStr


class Notice(_Model):
    """A plain sentence telling the user how the question was answered (1.2.0)."""

    kind: NoticeKind
    text: StrictStr


class Diagnostic(_Model):
    month: Month
    text: StrictStr
    source: DiagnosticSource


# ---------------------------------------------------------------------------
# Trace (7.4)
# ---------------------------------------------------------------------------

_L1_MSG = re.compile(
    rf"^L1 fired: (?P<issue>[^;]+); (?P<before>.+?) -> (?P<after>.+?); "
    rf"repair (?P<n>\d+) of {L1_CAP}$"
)
_L2_MSG = re.compile(
    rf"^L2 fired: coverage (?P<months>\d+)/{WINDOW_MONTHS} below (?P<need>\d+)/{WINDOW_MONTHS}; "
    rf"(?P<action>.+); attempt (?P<n>\d+) of {L2_CAP}$"
)
_L1_DATA_KEYS = {"issue", "before", "after", "repair_no", "cap"}
_L2_DATA_KEYS = {
    "coverage_months",
    "need_months",
    "action",
    "factor",
    "attempt",
    "cap",
    "effective_price_band",
    "decided_by",
}


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


class TraceEvent(_Model):
    i: Count
    agent: TraceAgent
    kind: TraceKind
    loop: LoopName | None
    msg: StrictStr
    data: dict[str, Any]

    @model_validator(mode="after")
    def _check(self) -> "TraceEvent":
        if self.kind != "loop":
            return self
        # Every loop firing carries the exact msg template and data keys (7.4).
        if self.loop == "L1":
            self._check_l1()
        elif self.loop == "L2":
            self._check_l2()
        else:
            raise ValueError("a kind='loop' event must have loop 'L1' or 'L2'")
        return self

    def _check_l1(self) -> None:
        m = _L1_MSG.match(self.msg)
        if not m:
            raise ValueError(f"L1 msg does not match the template: {self.msg!r}")
        if set(self.data) != _L1_DATA_KEYS:
            raise ValueError(f"L1 data keys must be {sorted(_L1_DATA_KEYS)}")
        d = self.data
        if d["issue"] != m["issue"]:
            raise ValueError("L1 data.issue must equal the issue in msg")
        if not _is_int(d["repair_no"]) or d["repair_no"] != int(m["n"]):
            raise ValueError("L1 data.repair_no must equal n in msg")
        if not 1 <= d["repair_no"] <= L1_CAP:
            raise ValueError(f"L1 repair_no must be in 1..{L1_CAP}")
        if d["cap"] != L1_CAP:
            raise ValueError(f"L1 data.cap must be {L1_CAP}")

    def _check_l2(self) -> None:
        m = _L2_MSG.match(self.msg)
        if not m:
            raise ValueError(f"L2 msg does not match the template: {self.msg!r}")
        if set(self.data) != _L2_DATA_KEYS:
            raise ValueError(f"L2 data keys must be {sorted(_L2_DATA_KEYS)}")
        d = self.data
        if not _is_int(d["coverage_months"]) or d["coverage_months"] != int(m["months"]):
            raise ValueError("L2 data.coverage_months must equal months in msg")
        if not _is_int(d["need_months"]) or d["need_months"] != int(m["need"]):
            raise ValueError("L2 data.need_months must equal need in msg")
        if d["need_months"] != COVERAGE_MIN_MONTHS:
            raise ValueError(f"L2 need_months must be {COVERAGE_MIN_MONTHS}")
        if d["coverage_months"] >= d["need_months"]:
            raise ValueError("L2 fires only when coverage_months < need_months")
        if d["action"] != m["action"]:
            raise ValueError("L2 data.action must equal action in msg")
        if not _is_int(d["attempt"]) or d["attempt"] != int(m["n"]):
            raise ValueError("L2 data.attempt must equal n in msg")
        if not 1 <= d["attempt"] <= L2_CAP:
            raise ValueError(f"L2 attempt must be in 1..{L2_CAP}")
        if d["cap"] != L2_CAP:
            raise ValueError(f"L2 data.cap must be {L2_CAP}")
        if d["factor"] != L2_WIDEN[d["attempt"] - 1]:
            raise ValueError(f"L2 factor for attempt {d['attempt']} must be {L2_WIDEN[d['attempt'] - 1]!r}")
        if d["decided_by"] not in ("rule", "llm"):
            raise ValueError("L2 data.decided_by must be 'rule' or 'llm'")
        band = d["effective_price_band"]
        if band is not None and not (
            isinstance(band, list)
            and len(band) == 2
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in band)
        ):
            raise ValueError("L2 data.effective_price_band must be null or [lo, hi]")


# ---------------------------------------------------------------------------
# Metadata (6.4)
# ---------------------------------------------------------------------------


class LoopCounters(_Model):
    L1_repairs: Annotated[StrictInt, Field(ge=0, le=L1_CAP)]
    L2_attempts: Annotated[StrictInt, Field(ge=0, le=L2_CAP)]


class LLMInfo(_Model):
    backend: StrictStr
    build: StrictStr
    launch_flags: Union[StrictStr, list[StrictStr]]
    gguf_sha256: Sha256
    quant: StrictStr
    ctx: Annotated[StrictInt, Field(ge=1)]
    temperature: Real
    seed: StrictInt
    prompt_hash: StrictStr


class Metadata(_Model):
    contract_version: StrictStr
    logic_version: StrictStr  # git short hash (CONTRACT.md 6.4)
    snapshot_sha256: Sha256
    seed: StrictInt
    llm_mode: LlmMode
    topology: Topology | None  # null only before a plan exists (error reports)
    n_scanners: Annotated[StrictInt, Field(ge=1)] | None
    loops_enabled: StrictBool
    loop_counters: LoopCounters
    partial_last_month: StrictBool
    llm: LLMInfo | None


# ---------------------------------------------------------------------------
# TrendReport (6.2)
# ---------------------------------------------------------------------------


def expected_record_keys(criteria: Criteria) -> set[tuple[str, str]]:
    """Dense-grid key set (I-DENSE): depends only on the criteria."""
    assert criteria.window_end is not None
    locs = (
        set(criteria.localities)
        if criteria.localities is not None
        else set(CANONICAL_LOCALITIES)
    )
    return {(m, r) for m in window_months(criteria.window_end) for r in {ALL_REGION} | locs}


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)


class TrendReport(_Model):
    status: Status
    error: ErrorInfo | None
    criteria_in: Criteria | None  # null only on an error before any criteria exist
    effective_criteria: Criteria | None
    price_unit: PriceUnit
    records: list[TrendRecord]
    summary: Summary | None
    coverage_score: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    anomaly_flags: list[AnomalyFlag]
    diagnostics: list[Diagnostic]
    notices: list[Notice] = Field(default_factory=list)  # 1.2.0; also on error reports
    trace: list[TraceEvent]
    metadata: Metadata

    @model_validator(mode="after")
    def _check(self) -> "TrendReport":
        self._check_trace_and_counters()
        if self.status == "error":
            self._check_error()
        else:
            self._check_ok()
        return self

    # -- trace and loop bookkeeping (7.2 I-CAP, 7.4) --------------------------

    def _check_trace_and_counters(self) -> None:
        for expected_i, ev in enumerate(self.trace):
            if ev.i != expected_i:
                raise ValueError(f"trace[{expected_i}].i must be {expected_i}, got {ev.i}")
        l1 = sum(1 for e in self.trace if e.kind == "loop" and e.loop == "L1")
        l2 = sum(1 for e in self.trace if e.kind == "loop" and e.loop == "L2")
        lc = self.metadata.loop_counters
        if (lc.L1_repairs, lc.L2_attempts) != (l1, l2):
            raise ValueError(
                f"loop_counters {(lc.L1_repairs, lc.L2_attempts)} must equal the number "
                f"of loop events in the trace {(l1, l2)}"
            )
        if not self.metadata.loops_enabled and (l1 or l2):
            raise ValueError("loops_enabled is false but loop events were recorded")

    # -- error reports (6.5) --------------------------------------------------

    def _check_error(self) -> None:
        if self.error is None:
            raise ValueError("status 'error' requires an error object")
        if self.records != [] or self.summary is not None or self.coverage_score != 0:
            raise ValueError("an error report has records=[], summary=null, coverage_score=0")
        if self.anomaly_flags or self.diagnostics:
            raise ValueError("an error report has no anomaly_flags or diagnostics")
        if not self.trace:
            raise ValueError("an error report still has a filled trace")

    # -- ok reports -----------------------------------------------------------

    def _check_ok(self) -> None:
        if self.error is not None:
            raise ValueError("status 'ok' requires error=null")
        if self.criteria_in is None or self.effective_criteria is None:
            raise ValueError("an ok report needs criteria_in and effective_criteria")
        eff = self.effective_criteria
        if eff.window_end is None:
            raise ValueError("effective_criteria.window_end must be resolved")
        bad = eff.domain_violations()
        if bad:
            raise ValueError(f"effective_criteria is not valid: {bad}")
        if self.price_unit != eff.price_unit:
            raise ValueError("price_unit must equal effective_criteria.price_unit")
        if self.summary is None:
            raise ValueError("an ok report has a summary object")
        if self.metadata.topology is None or self.metadata.n_scanners is None:
            raise ValueError("an ok report records topology and n_scanners")

        keys = [(r.month, r.region_key) for r in self.records]
        if len(set(keys)) != len(keys):
            raise ValueError("records contain a duplicate (month, region_key)")
        if set(keys) != expected_record_keys(eff):
            raise ValueError("records must be the dense grid of effective_criteria (I-DENSE)")

        all_series = sorted(
            (r for r in self.records if r.region_key == ALL_REGION), key=lambda r: r.month
        )
        self._check_coverage_and_summary(all_series)
        self._check_pct_change(all_series)
        self._check_flags(all_series)

    def _check_coverage_and_summary(self, all_series: list[TrendRecord]) -> None:
        covered = sum(1 for r in all_series if r.n_in_bucket >= MIN_BUCKET_N)
        if self.coverage_score != covered / WINDOW_MONTHS:
            raise ValueError(
                f"coverage_score must be {covered}/{WINDOW_MONTHS} (months with "
                f"n_in_bucket >= {MIN_BUCKET_N} on the ALL series)"
            )
        assert self.summary is not None
        if self.summary.n_rows != sum(r.listing_count for r in all_series):
            raise ValueError("summary.n_rows must equal the sum of ALL listing_count")

    def _check_pct_change(self, all_series: list[TrendRecord]) -> None:
        for t, cur in enumerate(all_series):
            if t == 0:
                expected: float | None = None  # first month of a window is always null
            else:
                prev = all_series[t - 1]
                if prev.n_in_bucket >= MIN_BUCKET_N and cur.n_in_bucket >= MIN_BUCKET_N:
                    assert prev.median_price_per_sqft and cur.median_price_per_sqft is not None
                    expected = cur.median_price_per_sqft / prev.median_price_per_sqft - 1
                else:
                    expected = None
            got = cur.pct_change_price_per_sqft
            if (expected is None) != (got is None) or (
                expected is not None and got is not None and abs(expected - got) > ABS_TOL
            ):
                raise ValueError(
                    f"pct_change_price_per_sqft at {cur.month} must be {expected!r}, got {got!r}"
                )

    def _check_flags(self, all_series: list[TrendRecord]) -> None:
        expected: dict[tuple[str, str], float] = {}
        for t in range(1, len(all_series)):
            prev, cur = all_series[t - 1], all_series[t]
            pct = cur.pct_change_price_per_sqft
            if pct is not None and abs(pct) > ANOMALY_PCT:
                expected[(cur.month, "price_jump")] = pct
            if prev.n_in_bucket >= MIN_BUCKET_N and cur.listing_count <= COUNT_DROP * prev.listing_count:
                expected[(cur.month, "count_drop")] = cur.listing_count / prev.listing_count
        got = {(f.month, f.kind): f.value for f in self.anomaly_flags}
        if len(got) != len(self.anomaly_flags):
            raise ValueError("anomaly_flags contain a duplicate (month, kind)")
        if set(got) != set(expected):
            raise ValueError(
                f"anomaly_flags must be {sorted(expected)} (6.3), got {sorted(got)}"
            )
        for k, v in expected.items():
            if not _close(got[k], v):
                raise ValueError(f"anomaly flag {k} value must be {v}, got {got[k]}")
        # One diagnostic per flag (7.1).
        if sorted(d.month for d in self.diagnostics) != sorted(m for m, _ in expected):
            raise ValueError("diagnostics must have exactly one entry per anomaly flag")


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def report_to_json(report: TrendReport) -> str:
    """Report as JSON: model field order, shortest round-trip floats, no rounding (I-FLOAT)."""
    return json.dumps(
        report.model_dump(mode="json"), separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


__all__ = [n for n in dir() if not n.startswith("_") and n not in {"annotations"}]
