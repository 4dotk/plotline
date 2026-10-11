# Agent F — Reporter

*Shard of `agents.md` v1.1.0. Read **this file and `_common.md` only**. `CONTRACT.md` wins on any conflict.*

**Kind:** worker (plain function)

**Constants** (reading only; import from `app/contract.py`, never retype): (none; reads CONTRACT_VERSION)

**Types:** `from app.contract import TrendReport, Metadata, LoopCounters, ErrorInfo, TraceEvent`


**Job:** assemble the `TrendReport` for the API and UI. **LLM:** none. **May change:** nothing numeric.

**Does**
* Fill every field of global 6.2 and `metadata` (6.4): `contract_version`, `logic_version`, `snapshot_sha256`, `seed`, `llm_mode`, `topology`, `n_scanners`, `loops_enabled`, `loop_counters`, `partial_last_month`, `llm`.
* `price_unit` = copy of `effective_criteria.price_unit`. `criteria_in` = request as received.
* `loop_counters` = `{L1_repairs, L2_attempts}`, equal to the number of `kind = "loop"` trace events for each loop (I-CAP).
* `partial_last_month = true` when the window ends at the latest month; the partial month is reported, never "fixed".
* Serialise to byte-identical JSON for the same (`query`, `listings_df`, `seed`, `options`) when `LLM_MODE` ∈ {off, replay} (I-DET): fixed key order, shortest round-trip floats, no rounding, no wall-clock time (I-FLOAT).
* **On any error:** `status = "error"`, `error = {code, message}`, `records = []`, `summary = null`, `coverage_score = 0`, `trace` still filled.

**Must not:** compute or alter any number, call the LLM, or read the clock.

## Tests for this agent

Error report shape (`records = []`, `summary = null`, `coverage_score = 0`, trace filled); metadata fields; byte-identical JSON on two runs (I-DET); `trace.i` consecutive from 0
