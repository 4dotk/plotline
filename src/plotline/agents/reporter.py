"""Agent F: Reporter. Assembles the ``TrendReport``; computes nothing."""

from __future__ import annotations

from plotline.contract import (
    CONTRACT_VERSION,
    AnomalyFlag,
    Criteria,
    Diagnostic,
    ErrorInfo,
    LLMInfo,
    LlmMode,
    LoopCounters,
    Metadata,
    Summary,
    Topology,
    TraceEvent,
    TrendRecord,
    TrendReport,
)


def build_report(
    *,
    error: ErrorInfo | None,
    criteria_in: Criteria | None,
    effective: Criteria | None,
    records: list[TrendRecord],
    summary: Summary | None,
    coverage_score: float,
    flags: list[AnomalyFlag],
    diagnostics: list[Diagnostic],
    trace: list[TraceEvent],
    loop_counters: LoopCounters,
    seed: int,
    llm_mode: LlmMode,
    logic_version: str,
    snapshot_sha256: str,
    loops_enabled: bool,
    topology: Topology | None,
    n_scanners: int | None,
    partial_last_month: bool,
    llm: LLMInfo | None,
) -> TrendReport:
    """Build the report. ``TrendReport`` validates every contract relation, so a
    report that comes back from here is valid by construction (a bad one raises)."""
    if error is not None:  # 6.5: records=[], summary=null, coverage_score=0, trace filled
        records, summary, coverage_score, flags, diagnostics = [], None, 0, [], []
    unit_source = effective or criteria_in
    return TrendReport(
        status="error" if error is not None else "ok",
        error=error,
        criteria_in=criteria_in,
        effective_criteria=effective,
        price_unit=unit_source.price_unit if unit_source is not None else "inr",
        records=records,
        summary=summary,
        coverage_score=coverage_score,
        anomaly_flags=flags,
        diagnostics=diagnostics,
        trace=trace,
        metadata=Metadata(
            contract_version=CONTRACT_VERSION,
            logic_version=logic_version,
            snapshot_sha256=snapshot_sha256,
            seed=seed,
            llm_mode=llm_mode,
            topology=topology,
            n_scanners=n_scanners,
            loops_enabled=loops_enabled,
            loop_counters=loop_counters,
            partial_last_month=partial_last_month,
            llm=llm,
        ),
    )
