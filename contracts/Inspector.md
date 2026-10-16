# Agent H — Inspector

*Added in contract 1.2.0 (2026-10-16). Read **this file and `_common.md` only**. `CONTRACT.md` wins on any conflict.*

**Kind:** worker (plain function)

**Constants** (reading only; import from `app/contract.py`, never retype): BHK_VALUES = (1, 2, 3, 4) · WINDOW_MONTHS = 12 · CANONICAL_LOCALITIES

**Types:** `from app.contract import Criteria, Notice, ErrorInfo, TraceEvent`

**Job:** check every request against what the data holds before it is scanned, and tell the user how the question was answered. **LLM:** none.

**Why it exists** (`docs/design_changes.md` C23): each locality has its own data range (Adyar ends 2012-05), so before 1.2.0 "Adyar in 2023", "Adyar 3 BHK" and "Velachery 1 BHK" came back `ok` with 0 rows and no explanation, "Hyderabad" or "5bhk" was answered for all localities or all BHK without a word, and L1 repairs were visible only in the trace.

| | |
|---|---|
| **Inputs** | `effective_criteria`; `DataInfo` built from `listings_df` (first and latest month, and per locality its own first/last month, BHK values and sale count); at the end also the trace events, `criteria_in`, `listings_df` and the error, if any. |
| **Outputs** | Before the scan: nothing (in range), an L1 request to A, or a failure. At the end: `notices` (global 6.2). |
| **May change** | `notices` only. Never the criteria, the rows or any number. |

**Does**
1. **Before every scan** (the first and each one after an L1 repair): run the criteria check (`aggregator.validate_criteria`: `domain_violations()` plus the valid `window_end` range read from the data). In range → a `step` event. Repairable issues → one L1 request to A for all of them (a `warning` event naming the issues); A writes the L1 `loop` event. An inverted `sqft_range` → `E_INVALID_CRITERIA` at once. The repair table is in `_common.md`.
2. **At the end** (after G on `ok` runs; on every error report once `DataInfo` exists), build `notices` in this order:
   * one `repaired` notice per field each L1 `loop` event changed (window clamped: says the data's range and the valid `window_end`s; band swapped; BHK dropped; place matched);
   * one `not_read` notice per Planner `parse audit` warning;
   * on an error: one `out_of_scope` notice with the error message, without its `invalid <field>:` prefix; then stop;
   * one `widened` notice if L2 fired (says the widened band, or that the price filter was dropped);
   * one `no_sales` notice if any requested locality (all 7 if `localities` is null) has no rows for the hard filters (window, locality, BHK) in `listings_df`; for each such locality it says which BHK values and which months the data holds. The orchestrator also writes it as a `warning` event.
3. Text comes from templates. Every figure in it (months, rupees, BHK values) is computed by code from the data or the criteria; rupees are written in lakh below a crore and in crore above (display only; the report's numbers are unchanged, I-FLOAT).

**Must not**
* Change `effective_criteria`, repair anything (A's job), or widen (D's job).
* Call the model, or talk to D, E or G.
* Turn a valid request with no matching sales into an error: that is `ok` plus a `no_sales` notice (D12).

**Failure behaviour:** no error codes of its own beyond the criteria check above (`E_INVALID_CRITERIA` through the orchestrator when A cannot repair or `L1_CAP` is reached).

## Tests for this agent

Present in `tests/unit/agents/test_inspector.py`: each locality's own range and BHK in `DataInfo`; a recent year repaired and said; a city not in the data refused (`out_of_scope`); a BHK above the data refused, some BHK dropped and said; a band given high to low; H acts before the scan; a BHK a locality never sold, and only the empty locality named (`no_sales`); no notice when there are sales; L2 widening said; window out of range. MR11 (`contracts/Testing.md` §5) requires a `repaired` notice whenever L1 fires.

**Not tested at the freeze:** the `not_read` notice (the parse-audit warning itself is tested in `test_planner.py`), the `widened` text for a dropped band, and several issues repaired in one pass (MR11 covers this end to end).
