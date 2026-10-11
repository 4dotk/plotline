# Agent E — Anomaly Detector

*Shard of `agents.md` v1.1.0. Read **this file and `_common.md` only**. `CONTRACT.md` wins on any conflict.*

**Kind:** worker (plain function)

**Constants** (reading only; import from `app/contract.py`, never retype): MIN_BUCKET_N = 5 · ANOMALY_PCT = 0.12 · COUNT_DROP = 0.5 · FLAT_BAND_PCT = 1.0

**Types:** `from app.contract import TrendRecord, AnomalyFlag, Summary, StatChange`


**Job:** compute `pct_change_price_per_sqft`, `anomaly_flags` and `summary`. **LLM:** none.

| | |
|---|---|
| **Inputs** | `records` from C (after D has finished), the matching rows (for pooled summary medians), `effective_criteria`. |
| **Outputs** | `pct_change_price_per_sqft` on the `ALL` records, `anomaly_flags`, `summary`. |
| **May change** | Flags, summary, the `pct_change` field. |

**Does** (all on the `ALL` series, D5)
* `pct_change_price_per_sqft[t] = median_ppsf[t] / median_ppsf[t−1] − 1`, only when **both** months have `n_in_bucket ≥ MIN_BUCKET_N`; otherwise null. The first month is always null. Locality records stay null.
* **`price_jump`** at month t if `pct_change` is not null and `|pct_change| > ANOMALY_PCT` (strictly greater). `value` = that fraction, `threshold` = `ANOMALY_PCT`.
* **`count_drop`** at month t if month t−1 has `n_in_bucket ≥ MIN_BUCKET_N` **and** `listing_count[t] ≤ COUNT_DROP × listing_count[t−1]`. `value` = `listing_count[t] / listing_count[t−1]`, `threshold` = `COUNT_DROP`.
* The first month of a window is never flagged.
* Each flag: `{month, region_key: "ALL", kind, value, threshold, reason}`. `reason` is a deterministic template sentence, not an LLM text.
* **Summary** (about `ALL`): `n_rows` = rows matching the filters inside the window. For `price` and `price_per_sqft`: `start` = median of that statistic over the rows of the **first 3** months pooled; `end` = same over the **last 3** months (never an average of monthly medians); `change_pct = (end/start − 1) × 100`; `direction` = `up` if `change_pct` > `FLAT_BAND_PCT`, `down` if < −`FLAT_BAND_PCT`, else `flat`. Both `price` and `price_per_sqft` are null if either pooled set has fewer than `MIN_BUCKET_N` rows.
* All thresholds are ratios or counts from section 3 constants (I-UNIT): scaling prices by any k must not change any flag.

**Must not:** call the LLM, change `listing_count`/`n_in_bucket`/medians, round, read the clock, or look at rows outside the window.

**Failure behaviour:** no error codes of its own. Missing predecessor data gives null, never an exception.

## Tests for this agent

A1 flags (`price_jump` at 2014-12 and 2015-01, no `count_drop`) and summary; strict `>` boundary; first month never flagged; null predecessor rules; no flag changes when prices are scaled (I-UNIT)
