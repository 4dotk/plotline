"""Orchestrator: wires the agents, runs the loops, enforces the caps.

It has no domain logic of its own (agents.md): it never computes a statistic,
filter or threshold. Control flow (CONTRACT.md 7.3):

    A Planner -> B Scanners -> C Aggregator -> D Validator -> E Anomaly -> G Diagnostic -> F Reporter
       ^                          |                |
       +---- L1 (C -> A, cap) ----+                +---- L2 (D -> B, cap)

Domain problems come back as ``status = "error"`` reports (I-ERR). An unexpected
exception is a bug and propagates.
"""

from __future__ import annotations

import functools
import logging
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Union

import pandas as pd

from plotline.agents.reporter import build_report
from plotline.agents import default_agents
from plotline.contract import (
    L1_CAP,
    L2_CAP,
    Criteria,
    ErrorInfo,
    LlmMode,
    RunOptions,
    TrendReport,
)
from plotline.llm_client import LlmClient, LlmConfig, LlmSession
from plotline.log import logged_agents, orch_log
from plotline.snapshot import check_snapshot
from plotline.state import (
    SNAPSHOT_COLUMNS,
    AgentSet,
    DataInfo,
    Failure,
    L1Request,
    RunState,
)
from plotline.trace import TraceLog

_NO_SHA = "0" * 64  # placeholder hash for errors raised before any snapshot is known


def detect_logic_version() -> str:
    """Git short hash of the code (metadata.logic_version). Start-up only."""
    env = os.environ.get("LOGIC_VERSION")
    if env:
        return env
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
            cwd=Path(__file__).resolve().parent,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class Engine:
    """One configured application: agents + snapshot identity + LLM client.

    ``llm_mode`` without ``llm_client`` builds a client in that mode with no chat
    backend (enough for ``off`` and for the stub agents); a real client brings
    its own mode."""

    def __init__(
        self,
        snapshot_sha256: str,
        *,
        agents: AgentSet | None = None,
        llm_client: LlmClient | None = None,
        llm_mode: LlmMode | None = None,
        logic_version: str = "unknown",
        snapshot_error: str | None = None,
    ) -> None:
        if llm_client is None:
            llm_client = LlmClient(LlmConfig(mode=llm_mode or "off", model_tag="unset"))
        elif llm_mode is not None and llm_mode != llm_client.mode:
            raise ValueError(f"llm_mode {llm_mode!r} differs from the client's mode {llm_client.mode!r}")
        self.agents = logged_agents(agents or default_agents())
        self.snapshot_sha256 = snapshot_sha256
        self.snapshot_error = snapshot_error
        self.llm_client = llm_client
        self.llm_mode: LlmMode = llm_client.mode
        self.logic_version = logic_version

    @classmethod
    def from_data_dir(cls, data_dir: str | Path = "data", **kwargs) -> "Engine":
        """Start-up: recompute the snapshot hash and compare it to SNAPSHOT.sha256.
        On a mismatch every run returns ``E_SNAPSHOT_HASH`` (data contract 6)."""
        d = Path(data_dir)
        sha, err = check_snapshot(d / "chennai_snapshot.csv", d / "SNAPSHOT.sha256")
        if "llm_client" not in kwargs and "llm_mode" not in kwargs:
            kwargs["llm_client"] = LlmClient(LlmConfig.from_env())
        return cls(sha, snapshot_error=err, **kwargs)

    # ------------------------------------------------------------------ run

    def run(
        self,
        query: Union[Criteria, str],
        listings_df: pd.DataFrame,
        seed: int = 0,
        options: RunOptions = RunOptions(),
    ) -> TrendReport:
        q = query.model_dump_json() if isinstance(query, Criteria) else repr(query)
        orch_log.info("run start: seed=%s llm_mode=%s loops_enabled=%s input_rows=%d query=%s",
                      seed, self.llm_mode, options.loops_enabled, len(listings_df), q)
        report = self._run(query, listings_df, seed, options)
        lc = report.metadata.loop_counters
        level = logging.ERROR if report.status == "error" else logging.INFO
        orch_log.log(level, "run end: status=%s error=%s records=%d flags=%d trace_events=%d L1=%d L2=%d",
                     report.status, report.error.code if report.error else None, len(report.records),
                     len(report.anomaly_flags), len(report.trace), lc.L1_repairs, lc.L2_attempts)
        return report

    def _run(
        self,
        query: Union[Criteria, str],
        listings_df: pd.DataFrame,
        seed: int,
        options: RunOptions,
    ) -> TrendReport:
        st = RunState()
        llm = self.llm_client.session(seed)
        criteria_in = query if isinstance(query, Criteria) else None

        if self.snapshot_error is not None:
            return self._error(st, llm, options, seed, criteria_in, None, "reporter",
                               ErrorInfo(code="E_SNAPSHOT_HASH", message=self.snapshot_error))
        missing = [c for c in SNAPSHOT_COLUMNS if c not in listings_df.columns]
        if missing:  # C's rule, applied up front because A needs the month range
            return self._error(st, llm, options, seed, criteria_in, None, "aggregator",
                               ErrorInfo(code="E_SCHEMA", message=f"listings_df is missing columns: {missing}"))
        months = listings_df["sale_date"].str[:7]
        info = DataInfo(first_month=str(months.min()), latest_month=str(months.max()))

        # ---- A: plan -------------------------------------------------------
        res = self.agents.plan(query, info, options, seed, self.llm_mode, st.trace, llm)
        if isinstance(res, Failure):
            return self._error(st, llm, options, seed, criteria_in, None, "planner", res.error)
        st.plan = res
        criteria_in = res.criteria_in

        # ---- B -> C with loop L1 (C -> A) ----------------------------------
        while True:
            st.rows = self.agents.scan(st.plan, listings_df, st.trace)
            out = self.agents.aggregate(st.plan.effective, st.rows, listings_df, info, st.trace)
            if isinstance(out, Failure):
                return self._error(st, llm, options, seed, criteria_in, st.plan, "aggregator", out.error)
            if isinstance(out, L1Request):
                if not options.loops_enabled or st.l1_repairs >= L1_CAP:
                    msg = f"invalid {out.fields[0]}: {out.issues}"
                    return self._error(st, llm, options, seed, criteria_in, st.plan, "aggregator",
                                       ErrorInfo(code="E_INVALID_CRITERIA", message=msg))
                fixed = self.agents.repair(st.plan, out, info, options, st.l1_repairs, st.trace)
                if isinstance(fixed, Failure):
                    return self._error(st, llm, options, seed, criteria_in, st.plan, "planner", fixed.error)
                st.l1_repairs += 1
                self._check_counter(st, "L1")
                st.plan = fixed
                continue
            st.records = out
            break
        st.validated = st.plan.effective

        # ---- D with loop L2 (D -> B) ---------------------------------------
        while True:
            decision = self.agents.validate(
                st.records, st.plan.effective, st.validated, options, st.l2_attempts,
                self.llm_mode, seed, st.trace, llm,
            )
            if isinstance(decision, Failure):
                return self._error(st, llm, options, seed, criteria_in, st.plan, "validator", decision.error)
            if decision.widen_to is None:
                break
            if st.l2_attempts >= L2_CAP:
                raise RuntimeError(f"validator asked for L2 attempt {st.l2_attempts + 1} beyond the cap {L2_CAP}")
            st.l2_attempts += 1
            self._check_counter(st, "L2")
            st.plan = replace(st.plan, effective=decision.widen_to)
            st.rows = self.agents.scan(st.plan, listings_df, st.trace)
            out = self.agents.aggregate(st.plan.effective, st.rows, listings_df, info, st.trace)
            if isinstance(out, Failure):
                return self._error(st, llm, options, seed, criteria_in, st.plan, "aggregator", out.error)
            if isinstance(out, L1Request):
                raise RuntimeError("widening produced invalid criteria; L2 must never trigger L1")
            st.records = out

        # ---- E, G, F -------------------------------------------------------
        analysis = self.agents.analyse(st.records, st.rows, st.plan.effective, st.trace)
        diags = self.agents.diagnose(analysis.flags, analysis.records, self.llm_mode, seed, st.trace)
        if isinstance(diags, Failure):
            return self._error(st, llm, options, seed, criteria_in, st.plan, "diagnostic", diags.error)

        return build_report(
            error=None, criteria_in=criteria_in, effective=st.plan.effective,
            records=analysis.records, summary=analysis.summary,
            coverage_score=decision.coverage_score, flags=analysis.flags, diagnostics=diags,
            trace=st.trace.events, loop_counters=st.trace.loop_counters(), seed=seed,
            llm_mode=self.llm_mode, logic_version=self.logic_version,
            snapshot_sha256=self.snapshot_sha256, loops_enabled=options.loops_enabled,
            topology=st.plan.topology, n_scanners=st.plan.n_scanners,
            partial_last_month=st.plan.effective.window_end == info.latest_month, llm=llm.info,
        )

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _check_counter(st: RunState, loop: str) -> None:
        """I-CAP: every loop firing writes exactly one trace event."""
        c = st.trace.loop_counters()
        got, want = (c.L1_repairs, st.l1_repairs) if loop == "L1" else (c.L2_attempts, st.l2_attempts)
        if got != want:
            raise RuntimeError(f"{loop} fired {want} time(s) but the trace has {got} loop event(s)")

    def _error(self, st: RunState, llm: LlmSession, options: RunOptions, seed: int, criteria_in, plan,
               agent: str, error: ErrorInfo) -> TrendReport:
        st.trace.error(agent, f"{error.code}: {error.message}", code=error.code)
        return build_report(
            error=error, criteria_in=criteria_in, effective=plan.effective if plan else None,
            records=[], summary=None, coverage_score=0, flags=[], diagnostics=[],
            trace=st.trace.events, loop_counters=st.trace.loop_counters(), seed=seed,
            llm_mode=self.llm_mode, logic_version=self.logic_version,
            snapshot_sha256=self.snapshot_sha256 or _NO_SHA, loops_enabled=options.loops_enabled,
            topology=plan.topology if plan else None, n_scanners=plan.n_scanners if plan else None,
            partial_last_month=False, llm=llm.info,
        )


@functools.lru_cache(maxsize=1)
def _default_engine() -> Engine:
    return Engine.from_data_dir(
        os.environ.get("CHENNAI_DATA_DIR", "data"), logic_version=detect_logic_version()
    )


def run(
    query: Union[Criteria, str],
    listings_df: pd.DataFrame,
    seed: int = 0,
    options: RunOptions = RunOptions(),
) -> TrendReport:
    """Entry point of CONTRACT.md 5.1, on the default engine (real A-E, template Diagnostic)."""
    return _default_engine().run(query, listings_df, seed, options)
