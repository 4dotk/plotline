# AGENTS SUBCONTRACT — Chennai Housing-Trends Application

**Task:** T77 · **Parent:** `CONTRACT.md` v1.0.0 (the global contract)
**Scope:** each agent's responsibility, inputs, outputs, allowed and forbidden actions, failure behaviour, invariants, and tests.

> **Superseded as the working text (1.2.0 note).** This is the v1.0.0 combined file, kept for the record. The binding per-agent text is in the shards (`_common.md`, `Planner.md`, `Inspector.md`, `Aggregator.md`, `Validator.md`, `Anomaly.md`, `Diagnostic.md`, `Reporter.md`). Since 1.1.0 D may use the model (D11), and since 1.2.0 agent H (Inspector) owns L1 and writes `notices`; where this file says otherwise, the shards and `GLOBAL_CONTRACT.md` win.

This is a **subcontract**, not a separate global or shared contract. It is derived from `CONTRACT.md` sections 5–8 and MUST NOT contradict or redefine them. If this file and `CONTRACT.md` disagree, `CONTRACT.md` wins and this file is the defect. Constants are never written here as numbers of their own; they come from `app/contracts.py` (global section 3). Numbers quoted below are for reading only.

Where this file adds a detail the global contract leaves open, the line is marked **[clarification]** and listed in section 11 for the T79 contract check.

---

## 1. Rules for every agent

| Rule | Source |
|---|---|
| Plain functions of their inputs. No file, network or system-clock access (I-CLOCK). | global 5.1, 7.2 |
| No random numbers. Only `app/llm_client.py` may use a seed. | I-CLOCK, 5.1 |
| Never modify `listings_df` or the `Criteria` they receive; copy before changing anything (I-PURE). | 5.1 |
| Domain problems are returned as a `status = "error"` report with a code from global 6.5. They are never raised (I-ERR). An unexpected exception is a bug and MUST propagate, not be hidden in a fake report. | 6.5, 7.2 |
| No absolute rupee, sqft or count constants except those in global section 3 (I-UNIT). | 7.2 |
| No rounding and no float formatting of any value that goes into the report (I-FLOAT). | 7.2 |
| Output must not depend on input row order (I-ORDER): medians use sorted values, never running sums. | 7.2 |
| Count rows. Never deduplicate by `listing_id` or by content (D3, I-NODEDUPE). | D3 |
| Only A (Planner, AI mode) and G (Diagnostic) may call the LLM, and only through `app/llm_client.py` (I-LLM). Every number in the report comes from code. | global 8, I-LLM |

## 2. Agent A — Query Planner

**Job:** turn the request into valid `Criteria`; choose the scanner topology; in AI mode ask the LLM to parse the sentence. **LLM:** AI mode only.

| | |
|---|---|
| **Inputs** | `query` (`Criteria` or sentence), the valid month range and canonical locality set taken from `listings_df` (month range = min and max of `sale_date[:7]`), `options`, `seed`, and an L1 repair request from C (issue code, field). |
| **Outputs** | `effective_criteria`, `topology` (`parallel` or `consolidated`), `n_scanners`, trace events. |
| **May change** | `effective_criteria`, topology. Nothing else. |

**Does**
1. **Structured mode:** use the `Criteria` as given. Fill defaults: `localities` = null (all 7), `window_end` = latest month (D2), `price_unit` = `"inr"`. No LLM call.
2. **AI mode:** ask the LLM, through `llm_client`, for a `Criteria` and nothing else. "Last year", "past year", "last 12 months", "this year" all give `window_end` = latest snapshot month. A named month ("12 months ending March 2011") sets that `window_end`. Money words become INR (`1 crore` = 10,000,000; `1 lakh` = 100,000). Unparseable LLM output → fall back to the rule-based parser (the fallback is a `warning` trace event).
3. **Topology:** `parallel` when `localities` is null or has ≥ `TOPOLOGY_PARALLEL_MIN_LOCALITIES` names (then `n_scanners` = number of localities, 7 if null); otherwise `consolidated` with `n_scanners` = 1. `options.force_topology` overrides the choice.
4. **L1 repair** (when C sends an issue back): apply the repair table in section 5. All repairable issues found in one pass count as **one** repair. Re-choose the topology from the repaired criteria. The pipeline restarts from B.
5. `criteria_in` is the request exactly as received; A never edits it.

**Must not**
* Read, filter, count or summarise listing rows beyond the month range and locality set above.
* Produce any number except the fields of `Criteria`.
* Widen filters (that is D's loop, L2).
* Widen or repair **hard** fields silently: only the four L1 repairs exist.

**Failure behaviour**

| Situation | Result |
|---|---|
| AI mode with `LLM_MODE=off` | report `E_LLM_OFF` |
| AI mode, LLM and rule parser both fail | report `E_NL_UNPARSEABLE` |
| `LLM_MODE=replay` and the request is not in the cache | report `E_REPLAY_MISS` (never a silent live call) |
| `loops_enabled = false` and criteria invalid | report `E_INVALID_CRITERIA`, `message` names the field |
| Cannot repair, or `L1_CAP` reached | report `E_INVALID_CRITERIA`, `message` names the field |

## 3. Agent B — Scanners

**Job:** return the rows that match `effective_criteria`. **LLM:** none.

| | |
|---|---|
| **Inputs** | `effective_criteria`, `listings_df` (read-only), the scanner's partition (one locality, or all). |
| **Outputs** | A new dataframe of matching rows (a copy). |
| **May change** | The row set. Nothing else. |

**Does**
* Keep a row only if **all** hold:
  * `sale_date[:7]` lies in the 12-month window ending at `window_end` (inclusive);
  * `locality` is in `localities` (null = any);
  * `bhk` is in `bhk` (null = any);
  * `price_band` (null = no filter): `lo ≤ price ≤ hi`, inclusive both ends, in `price_unit`, no unit conversion;
  * `sqft_range` (null = no filter): `lo ≤ sqft ≤ hi`, inclusive;
  * `sale_cond` is in the list (null = any).
* List filters are compared as **sets**.
* **Parallel topology:** one scanner per locality; results are concatenated. **Consolidated:** one scanner for everything. The merge MUST NOT depend on scanner completion order (I-ORDER, I-TOPO): concatenate in a fixed order, and the aggregator never relies on row order.

**Must not**
* Compute medians, counts, percentages, flags or any statistic.
* Deduplicate, round, convert units, clean data, or drop a row for any reason except the filters above.
* Validate or repair criteria (C's job). If handed invalid criteria, B applies the filters literally and C discards the result.
* Change what it returns because of the topology: parallel and consolidated MUST return the same multiset of rows.

**Failure behaviour:** zero matching rows is **not** an error; B returns an empty dataframe. B has no error codes of its own.

## 4. Agent C — Result Aggregator

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
* `sqft_range` with `lo > hi` is not in the global repair table. **[clarification]** C treats it as `E_INVALID_CRITERIA` naming the field (see section 11).

**Aggregation**
* **Dense grid (I-DENSE):** one `TrendRecord` for every pair (month in window, region). Regions = `ALL` plus each locality in `effective_criteria.localities` (or all 7 if null). The key set depends **only** on `effective_criteria`, never on the data. Months with zero sales still get a record.
* `ALL` pools **all** rows that match the filters; it is not built from the localities' medians.
* `listing_count` = rows in the bucket. `n_in_bucket` = those rows with finite `price` > 0 and `sqft` > 0.
* `median_price` = median of `price` over the `n_in_bucket` rows; `median_price_per_sqft` = median of per-row `price / sqft` (float64 division). Even count → mean of the two middle values (numpy `median` semantics). Both null when `n_in_bucket` = 0. Sort values before taking the median.
* `low_sample` = `n_in_bucket < MIN_BUCKET_N`.
* Order: month ascending, `ALL` first, localities alphabetically. Consumers must not rely on it.

**Must not:** call the LLM, fill `pct_change_price_per_sqft`, set flags or the summary, widen or repair criteria itself (it only reports the issue to A), or drop rows.

## 5. Agent D — Coverage Validator

**Job:** compute `coverage_score`; decide retry or stop. **LLM:** none.

| | |
|---|---|
| **Inputs** | `records` (the `ALL` series), `effective_criteria`, the **original** `criteria` (as validated), `options.loops_enabled`, the L2 attempt count. |
| **Outputs** | `coverage_score`, and either "continue" or an L2 request to B with the next widened soft filters. |
| **May change** | Triggers L2. |

**Does**
* `coverage_months` = number of the 12 months whose `ALL` record has `n_in_bucket ≥ MIN_BUCKET_N`. `coverage_score = coverage_months / 12`. Uses the **`ALL` series only** (D4).
* The decision is on the **integer**: pass when `coverage_months ≥ COVERAGE_MIN_MONTHS`. Never compare the float.
* **L2 fires** when `coverage_months < COVERAGE_MIN_MONTHS`, `loops_enabled` is true, soft filters exist, and attempts < `L2_CAP`.
* **Widening** (D7: soft filters only: `price_band`, `sqft_range`, `sale_cond`; `localities`, `bhk` and `window_end` are never widened):
  * attempt 1: each range widened by `L2_WIDEN[0]` of its **original** width on each side; attempt 2: by `L2_WIDEN[1]`; attempt 3: all soft filters removed.
  * A range `[lo, hi]` widened by f becomes `[lo − f·(hi−lo), hi + f·(hi−lo)]`, lower end floored at 0.
  * Always measured from the **original** value, never cumulative.
  * `effective_criteria` always shows the widened values.
* Stop as soon as the test passes or `L2_CAP` is reached. At the cap, continue and report the low `coverage_score`.
* Worked check (global 7.4, Appendix A3): Adyar, 1 BHK, ₹70–90 lakh, `window_end` 2010-12 → rows 38 → 49 → 71, covered months 3 → 6 → 9, `L2_attempts` = 2.

**Trace** (exact templates, global 7.4). Each firing writes exactly one `kind = "loop"` event, `loop = "L2"`, agent `validator` **[clarification]**:

`L2 fired: coverage {months}/12 below {need}/12; {action}; attempt {n} of 3`
with `data` keys `coverage_months`, `need_months`, `action`, `factor`, `attempt`, `cap`, `effective_price_band`. `factor` mirrors `L2_WIDEN` (0.2, 0.5, `"drop"`).

**Failure / skip behaviour**

| Situation | Result |
|---|---|
| Coverage low, **no soft filters** | trace message `L2 skipped: nothing to widen`; continue; **not** an attempt, `L2_attempts` unchanged |
| Coverage low, `loops_enabled = false` | trace message `L2 disabled`; continue |
| Cap reached | continue with the low `coverage_score`; no error |

D never raises an error for low coverage.

## 6. Agent E — Anomaly Detector

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

## 7. Agent G — Diagnostic

**Job:** write a short plain-language reason for each flag. **LLM:** yes (template if `LLM_MODE=off`).

| | |
|---|---|
| **Inputs** | `anomaly_flags`, `records` (read-only, for the figures in the prompt), `llm_mode`, `seed`. |
| **Outputs** | `diagnostics`: a list of `{month, text, source}`, `source` ∈ {`llm`, `template`}. |
| **May change** | `diagnostics` only (I-LLM). |

**Does**
* One entry per flag (none when there are no flags, and then **no LLM call**).
* `LLM_MODE=off` → deterministic template text, `source = "template"`.
* `LLM_MODE` ∈ {live, replay} → ask through `llm_client` (temperature 0, JSON checked with pydantic, prompts in `app/prompts/*.md`). Malformed output → one `warning` trace event per failure, up to 2 retries, then the **template** text for that flag. Each fallback is logged.
* The numbers the model sees are passed in from code. The model may only change the **text**.

**Must not:** change any numeric field, add or remove a flag, change `status`, `records`, `summary` or `coverage_score`, or import an HTTP or LLM library (only `llm_client.py` does).

**Failure behaviour:** malformed LLM output never fails the run (template fallback). `LLM_MODE=replay` with an uncached prompt → `E_REPLAY_MISS` **[clarification, see section 11]**.

## 8. Agent F — Reporter

**Job:** assemble the `TrendReport` for the API and UI. **LLM:** none. **May change:** nothing numeric.

**Does**
* Fill every field of global 6.2 and `metadata` (6.4): `contract_version`, `application logic_version`, `snapshot_sha256`, `seed`, `llm_mode`, `topology`, `n_scanners`, `loops_enabled`, `loop_counters`, `partial_last_month`, `llm`.
* `price_unit` = copy of `effective_criteria.price_unit`. `criteria_in` = request as received.
* `loop_counters` = `{L1_repairs, L2_attempts}`, equal to the number of `kind = "loop"` trace events for each loop (I-CAP).
* `partial_last_month = true` when the window ends at the latest month; the partial month is reported, never "fixed".
* Serialise to byte-identical JSON for the same (`query`, `listings_df`, `seed`, `options`) when `LLM_MODE` ∈ {off, replay} (I-DET): fixed key order, shortest round-trip floats, no rounding, no wall-clock time (I-FLOAT).
* **On any error:** `status = "error"`, `error = {code, message}`, `records = []`, `summary = null`, `coverage_score = 0`, `trace` still filled.

**Must not:** compute or alter any number, call the LLM, or read the clock.

## 9. Trace and loop bookkeeping

* `trace` events are `{i, agent, kind, loop, msg, data}`; `i` counts from 0 with no gaps; `agent` ∈ `planner|scanner|aggregator|validator|anomaly|diagnostic|reporter`; `kind` ∈ `step|decision|loop|warning|error`.
* **Every loop firing is exactly one `kind = "loop"` event** with the exact templates of global 7.4:
  * L1: `L1 fired: {issue}; {before} -> {after}; repair {n} of 2`, `data` keys `issue`, `before`, `after`, `repair_no`, `cap`. Written by agent `planner` at the moment of repair **[clarification]**.
  * L2: see section 6.
* "L2 skipped" and "L2 disabled" are **not** loop firings: use `kind = "decision"` (skipped) and `kind = "warning"` (disabled), `loop = null` **[clarification]**, so counting `kind = "loop"` events always equals `loop_counters`.
* Caps are hard: `L1_CAP` = 2 repairs, `L2_CAP` = 3 attempts.
* Loop order: L1 can only fire before the first successful aggregation, because widening never produces an invalid criterion. So L2 never triggers L1.
* The snapshot hash check (`E_SNAPSHOT_HASH`) runs at start-up, before agent A; see `contracts/data.md`.

## 10. Clarifications this file adds (review at T79)

| # | Point | What this file says | Why it needs a look |
|---|---|---|---|
| 1 | Who writes widened soft filters into `effective_criteria` | D computes them; the orchestrator records them | Global 7.1 says D only "triggers L2" and A "may change" `effective_criteria` |
| 2 | `sale_cond` is soft but not a range | Retries 1 and 2 leave it unchanged; retry 3 removes it | If `sale_cond` is the only soft filter, attempts 1 and 2 rescan the same rows and still count as attempts |
| 3 | `sqft_range` with `lo > hi` | `E_INVALID_CRITERIA`, no repair | Global repair table covers only `price_band` |
| 4 | `E_REPLAY_MISS` inside Diagnostic | Whole report errors, as global 6.5 says, never a silent live call | Could instead fall back to the template; belongs in `contracts/llm.md` |
| 5 | Which agent writes the L1 / L2 events and the skipped / disabled messages | See section 10 | Global 7.4 fixes the loop `msg` and `data`, not `agent`, and not the skipped/disabled `kind` |

## 11. Agent tests (what must exist; MR detail lives in `contracts/testing.md`)

| Agent | Minimum tests |
|---|---|
| A Planner | Defaults filled; "last year" → 2015-02 (and the other three phrasings); money words → INR; topology = parallel for null / ≥ 3 localities, consolidated otherwise; `force_topology` override; `E_LLM_OFF`, `E_NL_UNPARSEABLE`, `E_REPLAY_MISS`; `criteria_in` never edited |
| B Scanners | Each filter in isolation, inclusive boundaries; set semantics for lists; parallel and consolidated give the same multiset of rows (I-TOPO); empty result is not an error; input dataframe unchanged (I-PURE) |
| C Aggregator | Golden vectors A1 and A2 (counts, medians, ppsf); dense grid keys depend only on `effective_criteria` (I-DENSE); zero-sale months have null medians; `ALL` is pooled; L1 issue detection and each repair; `E_SCHEMA` |
| D Validator | Coverage integer test at exactly 8 / 9 / 10 months; worked L2 example A3 (38 → 49 → 71 rows, 3 → 6 → 9 months, 2 attempts); widening from the original, floor at 0; cap stops at 3; "skipped" and "disabled" paths; `loop_counters` equals loop events |
| E Anomaly | A1 flags (`price_jump` at 2014-12 and 2015-01, no `count_drop`) and summary; strict `>` boundary; first month never flagged; null predecessor rules; no flag changes when prices are scaled (I-UNIT) |
| G Diagnostic | Template when off; one entry per flag; no entries and no LLM call when no flags; malformed output → warning, retries, template; only `diagnostics` differs between modes |
| F Reporter | Error report shape (`records = []`, `summary = null`, `coverage_score = 0`, trace filled); metadata fields; byte-identical JSON on two runs (I-DET); `trace.i` consecutive from 0 |
| Whole pipeline | I-DET, I-PURE, I-DENSE checked on every base (global 7.2); MR1–MR10 and X1 per `contracts/testing.md` |

## 12. Implementation note (not binding)

* Agents A–F are written as plain Python functions over pandas dataframes and pydantic models, so they can be unit-tested without a model.
* **LangChain** is used only where a model is called. Any LangChain chat-model class, prompt template or output parser lives **inside `app/llm_client.py`**, behind one function that takes a prompt and a response schema and returns validated JSON. No agent imports LangChain or an HTTP client (global section 8).
* If LangGraph is used to run the pipeline, it may only express the control flow of section 1 (nodes A–F, edges, the L1 and L2 cycles, the caps). It must not carry domain logic, and the node results must still reproduce I-DET with `LLM_MODE` ∈ {off, replay}. Confirm in `contracts/llm.md` how cache keys cover LangChain's own prompt formatting, so replay stays byte-exact.

## 13. Traceability to the global contract

| This file | Global contract |
|---|---|
| §1, §10 control flow, loops, trace | 7.3, 7.4, I-CAP |
| §2 rules for every agent | 5.1, 7.2, 8 |
| §3 Planner | 5.2, 5.4, 6.5, 7.1, 7.3, D2, D10 |
| §4 Scanners | 5.2, 7.1, D3, I-TOPO |
| §5 Aggregator | 6.2, 6.3, 7.3 (L1), I-DENSE, I-ORDER |
| §6 Validator | 3, 6.3, 7.3 (L2), 7.4, D4, D7 |
| §7 Anomaly | 3, 6.2, 6.3, D5, I-UNIT |
| §8 Diagnostic | 7.1, 8, I-LLM |
| §9 Reporter | 6.2, 6.4, 6.5, I-DET, I-FLOAT |
| §12 Tests | 9.2, 9.5, Appendix A |

*Version: 1.0.0 (tracks `CONTRACT.md` v1.0.0). Status: draft, pending agreement at the contract check (T79).*
