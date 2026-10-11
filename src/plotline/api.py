"""HTTP API (GLOBAL_CONTRACT.md section 10).

    GET  /api/health   status, llm_mode, snapshot_sha256, logic_version, contract_version
    GET  /api/meta     what the UI needs to build its filter panel and window picker
    POST /api/run      {criteria | nl_query, seed?, options?} -> TrendReport

Domain problems are HTTP 200 with a report whose ``status`` is ``"error"``
(I-ERR). A malformed request body is HTTP 422 (FastAPI default); an unexpected
exception is HTTP 500, which is a bug. The API does no statistics: every number
the UI shows comes from the engine, or (for ``/api/meta``) from counting the
frozen snapshot.

Run:  uv run python -m plotline.api        (reads .env, logs to console + plotline.log)
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Union

import pandas as pd
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, model_validator

from plotline import contract as C
from plotline.contract import Criteria, RunOptions, month_add, report_to_json
from plotline.log import configure_logging
from plotline.orchestrator import Engine, detect_logic_version
from plotline.state import SNAPSHOT_COLUMNS

log = logging.getLogger("plotline.api")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VALID_MODES = ("live", "replay", "off")


class RunRequest(BaseModel):
    """Body of ``POST /api/run``: exactly one of ``criteria`` / ``nl_query``."""

    model_config = ConfigDict(extra="forbid")

    criteria: Criteria | None = None
    nl_query: str | None = None
    seed: int | None = None
    options: RunOptions = RunOptions()

    @model_validator(mode="after")
    def _exactly_one(self) -> "RunRequest":
        if (self.criteria is None) == (self.nl_query is None):
            raise ValueError("send exactly one of 'criteria' or 'nl_query'")
        return self


def _data_dir(explicit: str | Path | None) -> Path:
    d = Path(explicit or os.environ.get("CHENNAI_DATA_DIR", "data"))
    if not (d / "chennai_snapshot.csv").exists() and (_REPO_ROOT / "data").exists():
        d = _REPO_ROOT / "data"  # started from another working directory
    return d


def build_meta(df: pd.DataFrame, snapshot_sha256: str) -> dict:
    """Everything ``GET /api/meta`` returns, counted from the snapshot (not hard-coded)."""
    months = df["sale_date"].str[:7]
    first, latest = str(months.min()), str(months.max())
    counts = months.value_counts()
    span, m = [], first
    while m <= latest:  # dense: months with no sales appear with count 0
        span.append(m)
        m = month_add(m, 1)
    active = df.assign(month=months).groupby("month")["locality"].agg(lambda s: sorted(set(s)))
    return {
        "localities": sorted(df["locality"].unique().tolist()),
        "bhk_values": sorted(int(b) for b in df["bhk"].unique()),
        "sale_conds": sorted(df["sale_cond"].unique().tolist()),
        "first_month": first,
        "latest_month": latest,
        "window_end_min": month_add(first, C.WINDOW_MONTHS - 1),
        "window_end_max": latest,
        "default_window_end": latest,  # D2: "last year" = latest month in the data
        "sales_per_month": [{"month": x, "count": int(counts.get(x, 0))} for x in span],
        "localities_active_by_month": [
            {"month": x, "localities": active.get(x, [])} for x in span
        ],
        "snapshot_sha256": snapshot_sha256,
        "constants": {
            "contract_version": C.CONTRACT_VERSION,
            "window_months": C.WINDOW_MONTHS,
            "min_bucket_n": C.MIN_BUCKET_N,
            "coverage_min_months": C.COVERAGE_MIN_MONTHS,
            "anomaly_pct": C.ANOMALY_PCT,
            "count_drop": C.COUNT_DROP,
            "flat_band_pct": C.FLAT_BAND_PCT,
            "l1_cap": C.L1_CAP,
            "l2_cap": C.L2_CAP,
            "l2_widen": list(C.L2_WIDEN),
            "topology_parallel_min_localities": C.TOPOLOGY_PARALLEL_MIN_LOCALITIES,
        },
        "partial_months": [first, latest],  # the first and last months are partial (4.4)
    }


def create_app(
    data_dir: str | Path | None = None,
    llm_mode: str | None = None,
    engine: Engine | None = None,
) -> FastAPI:
    """Build the app. Arguments are for tests; normally settings come from the environment."""
    d = _data_dir(data_dir)
    mode = llm_mode or os.environ.get("LLM_MODE", "off")
    if mode not in _VALID_MODES:
        raise ValueError(f"LLM_MODE must be one of {_VALID_MODES}, got {mode!r}")
    eng = engine or Engine.from_data_dir(d, llm_mode=mode, logic_version=detect_logic_version())
    df = pd.read_csv(d / "chennai_snapshot.csv")
    missing = [c for c in SNAPSHOT_COLUMNS if c not in df.columns]
    if missing:
        raise RuntimeError(f"snapshot is missing columns {missing}")
    meta = build_meta(df, eng.snapshot_sha256)
    default_seed = int(os.environ.get("LLM_SEED") or 0)
    log.info("api ready: data_dir=%s rows=%d llm_mode=%s snapshot_ok=%s sha=%s",
             d, len(df), eng.llm_mode, eng.snapshot_error is None, eng.snapshot_sha256)

    app = FastAPI(title="plotline", version=C.CONTRACT_VERSION)
    origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"],
    )

    @app.middleware("http")
    async def _log_requests(request: Request, call_next):
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("%s %s -> 500 (unhandled)", request.method, request.url.path)
            raise
        log.info("%s %s -> %d in %.1f ms", request.method, request.url.path,
                 response.status_code, (time.perf_counter() - t0) * 1000)
        return response

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "llm_mode": eng.llm_mode,
            "snapshot_sha256": eng.snapshot_sha256,
            "logic_version": eng.logic_version,
            "contract_version": C.CONTRACT_VERSION,
        }

    @app.get("/api/meta")
    def get_meta() -> dict:
        return meta

    @app.post("/api/run")
    def run(req: RunRequest) -> Response:
        query: Union[Criteria, str] = req.criteria if req.criteria is not None else req.nl_query
        seed = req.seed if req.seed is not None else default_seed
        log.info("run request: seed=%s options=%s query=%s", seed, req.options.model_dump_json(),
                 req.criteria.model_dump_json() if req.criteria is not None else repr(req.nl_query))
        report = eng.run(query, df, seed=seed, options=req.options)
        # the report's own canonical JSON, so identical inputs give identical bytes (I-DET)
        return Response(content=report_to_json(report), media_type="application/json")

    return app


app = create_app()


def main() -> None:
    from dotenv import load_dotenv
    import uvicorn

    load_dotenv()
    configure_logging(os.environ.get("PLOTLINE_LOG_FILE", "plotline.log"))
    global app
    app = create_app()  # rebuilt after .env is loaded
    uvicorn.run(app, host=os.environ.get("API_HOST", "127.0.0.1"),
                port=int(os.environ.get("API_PORT", "8000")), log_config=None)


if __name__ == "__main__":
    main()
