"""Internal run state and the agent interfaces used by the orchestrator.

These are *implementation* types, not part of the contract: the contract only
fixes the report and its parts (``src/plotline/contract.py``). Each agent is a plain
function; the orchestrator wires them through ``AgentSet`` so a stub can be
replaced by the real agent one at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, Union

import pandas as pd

from plotline.contract import (
    AnomalyFlag,
    Criteria,
    Diagnostic,
    ErrorInfo,
    LlmMode,
    RunOptions,
    Summary,
    Topology,
    TrendRecord,
    WINDOW_MONTHS,
    month_add,
)
from plotline.trace import TraceLog

if TYPE_CHECKING:
    from plotline.llm_client import LlmSession

SNAPSHOT_COLUMNS = ("listing_id", "locality", "sqft", "sale_date", "bhk", "sale_cond", "price")


@dataclass(frozen=True)
class LocalityProfile:
    """What the data holds for one locality: its sale months and BHK values."""

    name: str
    first_month: str
    last_month: str
    bhk: tuple[int, ...]
    n_sales: int


@dataclass(frozen=True)
class DataInfo:
    """What the agents may know about ``listings_df``: the month range and, per
    locality, its own month range and BHK values (1.2.0: the Inspector checks
    every request against this). An empty ``localities`` means "not profiled"."""

    first_month: str
    latest_month: str
    localities: tuple[LocalityProfile, ...] = ()

    @classmethod
    def from_df(cls, df: pd.DataFrame) -> "DataInfo":
        months = df["sale_date"].astype(str).str[:7]
        profiles = tuple(
            LocalityProfile(name=str(loc), first_month=str(m.min()), last_month=str(m.max()),
                            bhk=tuple(sorted(int(b) for b in g["bhk"].unique())), n_sales=len(g))
            for loc, g in df.assign(_m=months).groupby("locality", sort=True)
            for m in [g["_m"]]
        )
        return cls(first_month=str(months.min()), latest_month=str(months.max()), localities=profiles)

    def locality(self, name: str) -> LocalityProfile | None:
        return next((p for p in self.localities if p.name == name), None)

    @property
    def first_valid_end(self) -> str:
        """Earliest ``window_end`` with a full 12-month window inside the data (4.4)."""
        return month_add(self.first_month, WINDOW_MONTHS - 1)


@dataclass
class PlanResult:
    effective: Criteria
    topology: Topology
    n_scanners: int
    criteria_in: Criteria  # the request as received (parsed, in AI mode)


@dataclass(frozen=True)
class Failure:
    """A domain error returned by an agent (I-ERR: returned, never raised)."""

    error: ErrorInfo


@dataclass(frozen=True)
class L1Request:
    """C asks A to repair criteria (loop L1)."""

    issues: list[str]
    fields: list[str]


@dataclass
class CoverageDecision:
    coverage_months: int
    coverage_score: float
    widen_to: Criteria | None = None  # set when L2 fires; the validator has logged the event


@dataclass
class Analysis:
    records: list[TrendRecord]
    flags: list[AnomalyFlag]
    summary: Summary


class PlanFn(Protocol):
    def __call__(
        self, query: Union[Criteria, str], info: DataInfo, options: RunOptions,
        seed: int, llm_mode: LlmMode, trace: TraceLog, llm: "LlmSession",
    ) -> Union[PlanResult, Failure]: ...


class RepairFn(Protocol):
    def __call__(
        self, plan: PlanResult, request: L1Request, info: DataInfo, options: RunOptions,
        l1_repairs: int, trace: TraceLog,
    ) -> Union[PlanResult, Failure]: ...


class ScanFn(Protocol):
    def __call__(self, plan: PlanResult, df: pd.DataFrame, trace: TraceLog) -> pd.DataFrame: ...


class AggregateFn(Protocol):
    def __call__(
        self, effective: Criteria, rows: pd.DataFrame, df: pd.DataFrame, info: DataInfo,
        trace: TraceLog,
    ) -> Union[list[TrendRecord], L1Request, Failure]: ...


class ValidateFn(Protocol):
    def __call__(
        self, records: list[TrendRecord], effective: Criteria, original: Criteria,
        options: RunOptions, l2_attempts: int, llm_mode: LlmMode, seed: int, trace: TraceLog,
        llm: "LlmSession",
    ) -> Union[CoverageDecision, Failure]: ...


class AnalyseFn(Protocol):
    def __call__(
        self, records: list[TrendRecord], rows: pd.DataFrame, effective: Criteria, trace: TraceLog
    ) -> Analysis: ...


class DiagnoseFn(Protocol):
    def __call__(
        self, flags: list[AnomalyFlag], records: list[TrendRecord], llm_mode: LlmMode,
        seed: int, trace: TraceLog, llm: "LlmSession | None" = None,
    ) -> Union[list[Diagnostic], Failure]: ...


@dataclass
class AgentSet:
    """The six agents the orchestrator calls (F, the Reporter, is fixed code)."""

    plan: PlanFn
    repair: RepairFn
    scan: ScanFn
    aggregate: AggregateFn
    validate: ValidateFn
    analyse: AnalyseFn
    diagnose: DiagnoseFn


@dataclass
class RunState:
    """Mutable state of one run; lives only inside ``Engine.run``."""

    trace: TraceLog = field(default_factory=TraceLog)
    plan: PlanResult | None = None
    validated: Criteria | None = None  # criteria after L1, before any L2 widening
    rows: pd.DataFrame | None = None
    records: list[TrendRecord] = field(default_factory=list)
    l1_repairs: int = 0
    l2_attempts: int = 0
