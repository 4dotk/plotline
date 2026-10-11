# Agent C — Result Aggregator

*Shard of `agents.md` v1.1.0. Read **this file and `_common.md` only**. `CONTRACT.md` wins on any conflict.*

**Kind:** worker (plain function; it also validates criteria)

**Constants** (reading only; import from `app/contract.py`, never retype): MIN_BUCKET_N = 5 · L1_CAP = 2

**Types:** `from app.contract import Criteria, TrendRecord`


**Job:** validate criteria and rows; build the dense grid of monthly buckets with counts and medians. **LLM:** none.

| | |
|---|---|
| **Inputs** | `effective_criteria`, merged rows from B, the schema of `listings_df`. |
| **Outputs** | `records` (without `pct_change_price_per_sqft`, which E fills), or an L1 request to A. |
| **May change** | `records`. Nothing else. |

**Validation (before aggregating), L1 issue codes and their repairs (applied by A):**

| Issue code | Detected when | Repair |
|---|---|---|
| `band_inverted` | `price_band` has `lo > hi` | swap |
| `locality_unknown` | a locality is not canonical | closest canonical name (`difflib`, cutoff 0.8); no match → cannot repair |
| `window_out_of_range` | `window_end` outside the valid range | clamp to the nearest valid `window_end` |
| `bhk_out_of_range` | a value outside 1–4 | drop the bad value; empty list → cannot repair |

* A missing column in `listings_df` returns `E_SCHEMA` immediately (no L1).
* `sqft_range` with `lo > hi` is not in the global repair table. **[clarification]** C treats it as `E_INVALID_CRITERIA` naming the field (listed in `_review.md`).

**Aggregation**
* **Dense grid (I-DENSE):** one `TrendRecord` for every pair (month in window, region). Regions = `ALL` plus each locality in `effective_criteria.localities` (or all 7 if null). The key set depends **only** on `effective_criteria`, never on the data. Months with zero sales still get a record.
* `ALL` pools **all** rows that match the filters; it is not built from the localities' medians.
* `listing_count` = rows in the bucket. `n_in_bucket` = those rows with finite `price` > 0 and `sqft` > 0.
* `median_price` = median of `price` over the `n_in_bucket` rows; `median_price_per_sqft` = median of per-row `price / sqft` (float64 division). Even count → mean of the two middle values (numpy `median` semantics). Both null when `n_in_bucket` = 0. Sort values before taking the median.
* `low_sample` = `n_in_bucket < MIN_BUCKET_N`.
* Order: month ascending, `ALL` first, localities alphabetically. Consumers must not rely on it.

**Must not:** call the LLM, fill `pct_change_price_per_sqft`, set flags or the summary, widen or repair criteria itself (it only reports the issue to A), or drop rows.

## Tests for this agent

Golden vectors A1 and A2 (counts, medians, ppsf); dense grid keys depend only on `effective_criteria` (I-DENSE); zero-sale months have null medians; `ALL` is pooled; L1 issue detection and each repair; `E_SCHEMA`
