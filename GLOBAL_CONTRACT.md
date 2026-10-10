# GLOBAL CONTRACT — Chennai Housing-Trends Application

This is the GLOBAL CONTRACT and the single source of truth for project requirements and agent alignment. The application logic, API, UI, test suite, report, and every subcontract must comply with this file. If code or a subcontract disagrees with this file, the disagreement is a defect: update the conflicting code or subcontract, not the global rule, unless S and K formally approve a global-contract change.

**Words used:** The application logic is the component that produces the trend report; the test suite independently checks it. MUST = no exceptions. SHOULD = do it unless you write down why not. "Application" = the orchestrator plus its agents, called as a Python function. "Test suite" = the metamorphic test code that calls the application logic.

**Change rule:** nobody edits sections 3 to 9 alone. Open a changelog line (section 12), both agree, bump the version, and tell the other person. After the `v0-results` tag, contract changes are allowed only if the changelog explains what was wrong, because later you must explain every change in the report.

## Contract structure

This file is the **global contract** and the single source of truth for project-wide requirements.

Area-specific documents live under `contracts/`:
- `contracts/data.md` — data source, cleaning, frozen snapshot, and data-boundary requirements.
- `contracts/testing.md` — oracle, metamorphic relations, test inputs, tolerances, statistics, and result logging.
- `contracts/agents.md` — each agent's responsibility, inputs, outputs, restrictions, and failure behaviour.
- `contracts/llm.md` — model configuration, modes, cache, validation, retries, fallbacks, and logging.

These are **subcontracts**, not separate global or shared contracts. They may add detail for their area but must not contradict or redefine this file. If a subcontract conflicts with the global contract, this file takes precedence until the global contract is formally changed.

## 2. Decisions made in this contract

| ID | Decision | Alternative you could pick |
|---|---|---|
| D1 | **Real data only, no synthetic snapshot.** The seeded base-input generator must provide enough eligible cases for the required test counts. | Add a synthetic snapshot (cut-order item). |
| D2 | **Default `window_end` = latest month in the snapshot (2015-02)**, and "last year" resolves to it. The partial last month is flagged in metadata. Test suite base inputs do **not** use the default; they sample window ends (9.3). | Default to 2011-12 (all 7 localities, 1,300 rows) for a richer demo. Change the one constant `DEFAULT_WINDOW_END`. |
| D3 | **The application logic never deduplicates.** One row = one sale. | Dedup by `listing_id`. This breaks MR3 variant (b); see MR3. |
| D4 | **Coverage and the L2 loop use the all-locality (`ALL`) series only** (12 cells), not every locality-month cell. | Per-cell coverage would fire L2 on almost every default query and L2 could never fix a locality that has no sales. |
| D5 | **Anomalies are detected on the `ALL` series of median ₹/sqft** (price jump) and listing count (count drop). All thresholds are ratios. | Per-locality anomalies are too noisy at 5–10 sales per cell. |
| D6 | **Prices carry a unit.** Field `median_price` (not `median_price_inr`) plus `price_unit` ∈ {`inr`, `lakh`}. | Keep `_inr` in the name and break MR2. |
| D7 | **L2 widens only "soft" filters** (price band, sqft range, sale condition). Locality, BHK and window are "hard" and are never widened. | Widen everything. This silently changes what the user asked for. |
| D8 | **The single row with no bedroom count is dropped at freeze** (7,109 → 7,108 rows). | Keep it with `bhk = null`. This breaks MR10 additivity. |
| D9 | **Same-seed pairs:** a source run and its follow-up use the same seed value. | Independent seeds per run. |
| D10 | **Replay cache is keyed on a logical model tag** (`LLM_MODEL_TAG`), not the server's model name, because LM Studio and `llama serve` name the same model differently. | — |

The design note must change in these places: `median_price_inr` becomes `median_price` + `price_unit`; L3 is "stretch, not in the contract"; every agent gets a one-line description (section 7.1); `coverage_score` and `anomaly_flags` get the formulas in section 6.3.

---

## 3. Constants (one file: `app/contracts.py`)

No other file may contain these numbers. Everything else imports them.

| Name | Value | Meaning |
|---|---|---|
| `WINDOW_MONTHS` | 12 | Window length. Not user-changeable. |
| `DEFAULT_WINDOW_END` | `"latest"` → 2015-02 | See D2. |
| `MIN_BUCKET_N` | 5 | A bucket with fewer sales is `low_sample`. |
| `COVERAGE_MIN_MONTHS` | 9 | Need ≥ 9 of 12 months with ≥ `MIN_BUCKET_N` sales (0.75). Compared as an **integer** so 9/12 is never a float-boundary case. |
| `ANOMALY_PCT` | 0.12 | Flag a month if \|month-on-month change of median ₹/sqft\| > 0.12. On the unfiltered series this flags about 23 % of month pairs (131 pairs measured), so flags appear in real runs. |
| `COUNT_DROP` | 0.5 | Flag a month if its count ≤ 0.5 × the previous month's count. |
| `FLAT_BAND_PCT` | 1.0 | Summary direction is `flat` if \|change\| ≤ 1 %. |
| `L1_CAP` | 2 | Maximum parameter repairs. |
| `L2_CAP` | 3 | Maximum coverage retries. |
| `L2_WIDEN` | (0.20, 0.50, "drop") | Retry 1 widens each soft range by 20 % of its width on each side, retry 2 by 50 %, retry 3 removes soft filters. Always measured from the **original** value, never cumulative. |
| `TOPOLOGY_PARALLEL_MIN_LOCALITIES` | 3 | ≥ 3 localities (or `null` = all) → parallel scanners, else one consolidated scanner. |
| `REL_TOL` | 1e-9 | Relative tolerance for floats in MR comparisons. |
| `ABS_TOL` | 1e-9 | Absolute tolerance for fractions (percent changes as fractions). |
| `ABS_TOL_PCT` | 1e-7 | Absolute tolerance for values stored in percent (`change_pct`). |
| `SEEDS` | (101, 202, 303) | The k = 3 recorded seeds. |
| `GEN_SEED` | 42 | Seed for the base-input generator. |

---

## 4. Data contract

### 4.1 Files

| File | Content |
|---|---|
| `data/raw/Chennai_Housing_Sale.csv` | Original Kaggle file, committed unchanged. SHA256 `f7ba74d1e7aa4f7ad3bd66a8b4b9331d9bc5b8c135213289c4fd8391f6b96a64`. |
| `data/chennai_snapshot.csv` | **The frozen snapshot.** The only data the application logic and tests read. SHA256 `18487b6ff164507f254c7bca38f13be786523b1e3fec03dd457bffa866cb6209`, 7,108 rows. |
| `data/SNAPSHOT.sha256` | The hash above in one line. The application logic MUST recompute and compare it at start-up and refuse to run on a mismatch. |

Source: Kaggle "Chennai Housing Sales Price" (`kaggle.com/datasets/kunwarakash/chennai-housing-sales-price`). Check the licence text on that page and cite it in the report.

`python scripts/freeze_snapshot.py data/raw/Chennai_Housing_Sale.csv data/chennai_snapshot.csv` MUST print exactly the snapshot hash above. It was run twice and gave the same hash.

### 4.2 Cleaning rules (applied once, by the freeze script, never by the application logic)

| Rule | Action | Rows touched |
|---|---|---|
| R1 | Strip spaces in `AREA`. Map `Chrompt`, `Chrmpet`, `Chormpet` → `Chrompet`; `TNagar` → `T Nagar`; `Karapakam` → `Karapakkam`; `Ana Nagar`, `Ann Nagar` → `Anna Nagar`; `Velchery` → `Velachery`; `Adyr` → `Adyar`; `KKNagar` → `KK Nagar`. | 38 |
| R2 | Strip spaces in `SALE_COND`. Map `Adj Land` → `AdjLand`; `Ab Normal` → `AbNormal`; `Partiall`, `PartiaLl` → `Partial`. | 15 |
| R3 | Drop rows with no `N_BEDROOM`. | 1 |
| R4 | Parse `DATE_SALE` (`dd-mm-yyyy`) to ISO `yyyy-mm-dd`. Stop with an error if any date fails. | 0 failures |
| R5 | Keep only the 7 columns below. Sort by `listing_id`. Write with `\n` line ends, no index. | all |

The script asserts: 7 localities, 5 sale conditions, unique `listing_id`, price > 0, sqft > 0, `bhk` ∈ {1,2,3,4}.

### 4.3 Snapshot columns (the dataframe the application logic receives)

| Column | Type | Meaning | Source column |
|---|---|---|---|
| `listing_id` | str | Sale id, e.g. `P00001`. | `PRT_ID` |
| `locality` | str | One of the 7 canonical names. | `AREA` |
| `sqft` | int | Interior area in sq ft. | `INT_SQFT` |
| `sale_date` | str | `YYYY-MM-DD`. | `DATE_SALE` |
| `bhk` | int | 1–4. | `N_BEDROOM` |
| `sale_cond` | str | `AbNormal`, `AdjLand`, `Family`, `Normal Sale`, `Partial`. | `SALE_COND` |
| `price` | int or float | Sale price **in `criteria.price_unit`**. INR in the snapshot. | `SALES_PRICE` |

Canonical localities (sorted): `Adyar, Anna Nagar, Chrompet, KK Nagar, Karapakkam, T Nagar, Velachery`.

### 4.4 Time rules

* A sale belongs to the month of its `sale_date` (`sale_date[:7]`). No time zones.
* The window is the 12 calendar months ending at `window_end` inclusive: `window_end − 11 … window_end`.
* Valid `window_end` values: **2004-12 … 2015-02** (123 values), read from the data, not hard-coded. `GET /api/meta` publishes them.
* The application logic MUST NOT read the system clock. "Last year" always resolves to the snapshot's latest month (2015-02), never to today's date. (Invariant I-CLOCK.)
* 2004-01 and 2015-02 are partial months. `metadata.partial_last_month = true` when the window ends at the latest month. Do not "fix" the partial month; report it.

---

## 5. Input contract

### 5.1 Entry point

```python
run(query: Criteria | str, listings_df: pandas.DataFrame, seed: int = 0,
    options: RunOptions = RunOptions()) -> TrendReport
```

* `query` is a `Criteria` (structured mode) or a plain sentence (AI mode, goes through the LLM Planner).
* `listings_df` has exactly the columns of 4.3. The application logic MUST NOT read files, the network or the clock inside agents. The tests builds every transformed dataset as a new dataframe.
* The application logic MUST NOT change `listings_df` (copy before touching). The tests reuses dataframes, so a hidden mutation would look like an MR violation. (Invariant I-PURE.)
* `seed` only reaches the LLM client. With `LLM_MODE=off` it changes nothing (and the tests checks that).

### 5.2 `Criteria`

| Field | Type | Default | Rule |
|---|---|---|---|
| `localities` | list[str] or null | null = all 7 | Canonical names. Unknown names go to L1 (section 7.3). |
| `window_end` | `"YYYY-MM"` | latest month | Valid range in 4.4. Outside it goes to L1 (clamp). |
| `bhk` | list[int] or null | null = any | Values from 1–4. |
| `price_band` | [lo, hi] or null | null | **Soft.** Inclusive on both ends, in `price_unit`. `lo > hi` goes to L1 (swap). |
| `sqft_range` | [lo, hi] or null | null | **Soft.** Inclusive. |
| `sale_cond` | list[str] or null | null = any | **Soft.** Canonical names. |
| `price_unit` | `"inr"` or `"lakh"` | `"inr"` | A label for how to read `price`. The application logic does **no** unit conversion. 1 lakh = 100,000 INR, 1 crore = 10,000,000 INR (used by the NL Planner only). |

List filters are compared as **sets** (order and duplicates inside a list do not matter). Two criteria objects are "the same base input" when their canonical JSON is equal (keys sorted, lists sorted, numbers as written).

### 5.3 `RunOptions` (test hooks, defaults must reproduce normal behaviour)

| Field | Default | Use |
|---|---|---|
| `loops_enabled` | true | `false` turns L1 and L2 off (diagnosis step 3). Invalid criteria then return `E_INVALID_CRITERIA`; low coverage logs "L2 disabled" and continues. |
| `force_topology` | null | `"parallel"` or `"consolidated"` overrides the Planner's choice. Only the tests uses it. |

### 5.4 AI mode (sentence in)

The LLM Planner must turn a sentence into a `Criteria` and nothing else (section 8). "Last year", "past year", "last 12 months", "this year" all mean `window_end = latest month of the snapshot`. A sentence that names a month ("12 months ending March 2011") sets that `window_end`. Money words become INR (`1 crore` → 10000000). On unparseable output the Planner falls back to the rule-based parser; if that fails too the report has `status = "error"`, code `E_NL_UNPARSEABLE`.

---

## 6. Output contract

### 6.1 The 12-month trend (this is "the output" every MR talks about)

For each month of the window and each region, the trend is: **listing count, median price, median price per sqft**. For the whole window, the trend is also summarised as **first-3-months vs last-3-months change** in median price and median ₹/sqft. Plus a **coverage score** and **anomaly flags**. Nothing else is a trend statistic.

### 6.2 `TrendReport`

| Field | Type | Compared in MRs as | Meaning |
|---|---|---|---|
| `status` | `"ok"` or `"error"` | EXACT | |
| `error` | null or {`code`, `message`} | code EXACT, message IGNORE | Codes in 6.5. |
| `criteria_in` | Criteria | EXACT | The request as received. |
| `effective_criteria` | Criteria | EXACT | After L1 repairs and L2 widening. This is what was actually computed. |
| `price_unit` | str | EXACT | Copy of `effective_criteria.price_unit`. |
| `records` | list[TrendRecord] | per field, see 6.3 | Dense grid, see below. |
| `summary` | Summary or null | per field | |
| `coverage_score` | float | EXACT (integer ratio) | Section 6.3. |
| `anomaly_flags` | list[AnomalyFlag] | set EXACT on (`month`, `region_key`, `kind`), `value` REL | |
| `diagnostics` | list[{`month`, `text`, `source`}] | IGNORE | LLM or template text, UI only. |
| `trace` | list[TraceEvent] | IGNORE (used in diagnosis) | Section 7.4. |
| `metadata` | object | IGNORE by default. `loop_counters` drives the skip rules and diagnosis; `topology` is compared only in MR1 and X1. | Section 6.4. |

**Dense grid rule (I-DENSE).** `records` contains one record for every pair (month in window, region), including pairs with zero sales. The region set is `ALL` plus each locality in `effective_criteria.localities` (or all 7 if null). The set of keys depends **only** on `effective_criteria`, never on the data. Order: month ascending, then `ALL` first, then localities alphabetically. **Consumers MUST NOT rely on order**: the tests compares by key (`month`, `region_key`).

**`TrendRecord`**

| Field | Type | Comparator | Definition |
|---|---|---|---|
| `month` | `"YYYY-MM"` | key | |
| `region_key` | str | key | `"ALL"` or a canonical locality. `ALL` pools all rows that match the filters (not just the listed localities' sum of medians). |
| `listing_count` | int | EXACT | Rows matching all filters whose month is this month and region. |
| `n_in_bucket` | int | EXACT | Rows among those with a finite price > 0 and sqft > 0, i.e. rows used for the medians. Always ≤ `listing_count`; equal on snapshot data. |
| `median_price` | float or null | REL_TOL | Median of `price` over the `n_in_bucket` rows. Even count → mean of the two middle values. null if `n_in_bucket` = 0. |
| `median_price_per_sqft` | float or null | REL_TOL | Median of `price / sqft` per row (float64 division). null if `n_in_bucket` = 0. |
| `low_sample` | bool | EXACT | `n_in_bucket < MIN_BUCKET_N`. |
| `pct_change_price_per_sqft` | float or null | ABS_TOL | **`ALL` records only** (null for localities). `median_ppsf[t] / median_ppsf[t−1] − 1` when both months have `n_in_bucket ≥ MIN_BUCKET_N`, else null. The first month of a window is always null. |

**`Summary`** (always about the `ALL` region)

| Field | Comparator | Definition |
|---|---|---|
| `n_rows` | EXACT | Rows matching the filters inside the window. |
| `price`, `price_per_sqft` | each null or object | Both are null if the pooled first-3-months set or last-3-months set has fewer than `MIN_BUCKET_N` rows. |
| `.start` | REL_TOL | Median of that statistic over all rows of the **first 3** months of the window, pooled (not an average of monthly medians). |
| `.end` | REL_TOL | Same over the **last 3** months. |
| `.change_pct` | ABS_TOL_PCT | `(end / start − 1) × 100`. In percent. |
| `.direction` | EXACT | `up` if `change_pct` > 1, `down` if < −1, else `flat`. |

**Comparator definitions.** EXACT: `==`. REL_TOL: `|a−b| ≤ REL_TOL × max(|a|,|b|)`, and null equals null only. ABS_TOL: `|a−b| ≤ ABS_TOL`. Exception: MR1 compares floats bit for bit (6.6, I-ORDER).

### 6.3 Formulas that the tests oracle re-implements

* **`coverage_score`** = (number of the 12 months whose `ALL` record has `n_in_bucket ≥ MIN_BUCKET_N`) / 12. The loop test is on the integer count: need `≥ COVERAGE_MIN_MONTHS` (9).
* **`anomaly_flags`**, all on the `ALL` series, each item `{month, region_key: "ALL", kind, value, threshold, reason}`:
  * `price_jump` at month t if `pct_change_price_per_sqft[t]` is not null and `|…| > ANOMALY_PCT`. `value` = that fraction.
  * `count_drop` at month t if month t−1 has `n_in_bucket ≥ MIN_BUCKET_N` and `listing_count[t] ≤ COUNT_DROP × listing_count[t−1]`. `value` = `listing_count[t] / listing_count[t−1]`.
  * The first month of a window can never be flagged.
* **Medians** use the standard definition (numpy `median` semantics). No interpolation options, no trimmed or weighted medians.
* **No rounding** anywhere in the application logic. Rounding is for the UI only. (Rounding would turn small float noise into false MR violations.)

### 6.4 `metadata`

`contract_version`, `application logic_version` (git short hash), `snapshot_sha256`, `seed`, `llm_mode`, `topology` (`parallel` | `consolidated`), `n_scanners`, `loops_enabled`, `loop_counters` = {`L1_repairs`, `L2_attempts`}, `partial_last_month` (bool), `llm` (null, or {`backend`, `build`, `launch_flags`, `gguf_sha256`, `quant`, `ctx`, `temperature`, `seed`, `prompt_hash`}).

### 6.5 Error codes

A domain error is **a report with `status = "error"`, never an exception** (I-ERR). Crashes are bugs.

| Code | When |
|---|---|
| `E_INVALID_CRITERIA` | Still invalid after `L1_CAP` repairs, or `loops_enabled = false`. `message` names the field. |
| `E_NL_UNPARSEABLE` | AI mode: LLM and rule parser both failed. |
| `E_LLM_OFF` | AI mode requested with `LLM_MODE=off`. |
| `E_REPLAY_MISS` | `LLM_MODE=replay` and the request is not in the cache. Never fall back to a live call silently. |
| `E_SCHEMA` | `listings_df` is missing a column of 4.3. |
| `E_SNAPSHOT_HASH` | Snapshot file does not match `data/SNAPSHOT.sha256`. |

On an error: `records = []`, `summary = null`, `coverage_score = 0`, `trace` still filled.

---

## 7. Behaviour contract

### 7.1 Agents and who may do what

| Agent | One-line job | LLM? | May change |
|---|---|---|---|
| A Query Planner | Turns the request into valid `Criteria`; picks the scanner topology; in AI mode asks the LLM to parse the sentence. | AI mode only | `effective_criteria`, topology |
| B Scanners | Return the rows matching `effective_criteria`. One scanner per locality (parallel) or one for all (consolidated); results merged. | No | Row set |
| C Result Aggregator | Validates criteria and rows; builds the dense grid of monthly buckets, medians and counts. | No | `records` |
| D Coverage Validator | Computes `coverage_score`; decides retry or stop. | No | Triggers L2 |
| E Anomaly Detector | Computes `pct_change_price_per_sqft`, `anomaly_flags`, `summary`. | No | Flags, summary |
| G Diagnostic | Writes a short plain-language reason for each flag. | Yes (template if LLM off) | `diagnostics` only |
| F Reporter | Assembles the `TrendReport` for the API and UI. | No | Nothing numeric |

### 7.2 Invariants (every run, every mode; the tests checks I-DET, I-PURE, I-DENSE for free)

| ID | Rule |
|---|---|
| I-DET | With `LLM_MODE` ∈ {off, replay}, the same (`query`, `listings_df`, `seed`, `options`) gives a **byte-identical JSON** report. Fields allowed to differ: none. (No wall-clock timing inside the report; log timing elsewhere.) |
| I-ORDER | Output does not depend on input row order. Medians are computed on sorted values, never on running sums that depend on order. |
| I-TOPO | Output does not depend on topology. Parallel and consolidated scanning give identical `records`. Topology appears only in `metadata`. |
| I-LLM | The LLM can change only (a) which `Criteria` the Planner produces in AI mode and (b) the text in `diagnostics`. **Every number comes from code.** |
| I-UNIT | The application logic has no absolute rupee, sqft or count constants except those in section 3. Every threshold is a ratio, a count, or taken from the criteria. Scaling prices must not change any flag. |
| I-NODEDUPE | The application logic counts rows. Duplicate rows and duplicate `listing_id`s are counted. |
| I-PURE | The application logic never modifies `listings_df` or the `Criteria` object it was given. |
| I-DENSE | The key set of `records` depends only on `effective_criteria`. |
| I-CLOCK | No system clock, no random numbers outside the LLM client. |
| I-CAP | Each loop has a hard cap. Every loop firing writes exactly one trace event, and `loop_counters` equals the number of such events. |
| I-ERR | Domain problems return `status = "error"`; the application logic does not raise. |
| I-FLOAT | No rounding, no float formatting, in the report. JSON uses the shortest round-trip form. |

### 7.3 Control flow (what the design note draws)

```
A Planner ══▶ B Scanners ──▶ C Aggregator ──▶ D Validator ──▶ E Anomaly ──▶ G Diagnostic ──▶ F Reporter
   ▲   (⇒ dependency: A's      ▲      │              │
   │    topology choice        │      │              └── L2: coverage low, widen soft filters, rescan (cap 3)
   │    changes what B does)   └──────┼──────────────────────┘  (D sends work back to B)
   └──────── L1: invalid criteria, repair and restart (cap 2) ──┘  (C sends work back to A)
```
* **L1 Parameter Repair (C → A), feedback loop.** C finds invalid criteria and sends them back to A with a code. A repairs and the pipeline restarts from B. Cap `L1_CAP` = 2 repairs.

  | Issue (code) | Repair |
  |---|---|
  | `band_inverted` (`lo > hi`) | swap |
  | `locality_unknown` | map to the closest canonical name (difflib, cutoff 0.8); no match → cannot repair |
  | `window_out_of_range` | clamp to the nearest valid `window_end` |
  | `bhk_out_of_range` | drop the bad value; empty result → cannot repair |

  All repairable issues in one pass count as **one** repair. Cannot repair, or cap reached → `E_INVALID_CRITERIA`.
* **L2 Coverage Retry (D → B), conditional/iterative step.** If (months with `n_in_bucket ≥ MIN_BUCKET_N`) < `COVERAGE_MIN_MONTHS`: apply the next step of `L2_WIDEN` to the original soft filters, rescan, re-aggregate, re-check. Stop as soon as the test passes or `L2_CAP` is reached (then continue and report the low `coverage_score`). If the criteria have **no soft filters**, write `L2 skipped: nothing to widen` and continue. This does not count as an attempt.
  * Widening a range `[lo, hi]` by factor f: `[lo − f·(hi−lo), hi + f·(hi−lo)]` (lower end floored at 0). Step 3 removes `price_band`, `sqft_range`, `sale_cond`.
  * `effective_criteria` always shows the widened values, so a reader can see what was really computed.
* **Dependency (A ⇒ B).** The topology A chooses changes what B *does* (how many scanners, how they split the work), not just the data it receives. I-TOPO says the numbers must not change.
* **L3** (Anomaly → Scanners) is **stretch and not in this contract.** Do not draw it.

### 7.4 Trace

`trace` is a list of events `{i, agent, kind, loop, msg, data}`. `i` counts from 0; `agent` ∈ `planner|scanner|aggregator|validator|anomaly|diagnostic|reporter`; `kind` ∈ `step|decision|loop|warning|error`; `loop` is `L1`, `L2` or null.

Every loop firing MUST be a `kind = "loop"` event with these exact `msg` templates and `data` keys (the report's execution trace is copied from here):

| Loop | `msg` template | `data` keys |
|---|---|---|
| L1 | `L1 fired: {issue}; {before} -> {after}; repair {n} of 2` | `issue`, `before`, `after`, `repair_no`, `cap` |
| L2 | `L2 fired: coverage {months}/12 below {need}/12; {action}; attempt {n} of 3` | `coverage_months`, `need_months`, `action`, `factor`, `attempt`, `cap`, `effective_price_band` |

**Worked L2 example (real data, checked by hand against the snapshot).** Query: Adyar, 1 BHK, price band ₹70–90 lakh (7,000,000–9,000,000), `window_end` 2010-12.
* First scan: 38 rows, 3 of 12 months have ≥ 5 sales (coverage 0.25).
* Attempt 1: band → 6,600,000–9,400,000 (+20 % of width 2,000,000 each side): 49 rows, 6 of 12 months.
* Attempt 2: band → 6,000,000–10,000,000 (+50 %): 71 rows, 9 of 12 months → passes (9 ≥ 9). Stop. `loop_counters.L2_attempts = 2`.

The application logic must reproduce those three numbers. Use it as the first test of L2.

---

## 8. LLM contract

* Only **one module** (`app/llm_client.py`, owner K) may talk to a model. Nothing else imports an HTTP library for this.
* Used in two places only: Planner (AI mode) and Diagnostic. Temperature 0. Output is JSON checked with pydantic. Malformed output → one `warning` trace event, up to 2 retries, then the rule-based Planner or the Diagnostic template. Each fallback is logged.
* Settings come from `.env` only. Commit `.env.example`, never `.env`.

| Key | Meaning |
|---|---|
| `LLM_MODE` | `live` calls the model; `replay` answers from the committed cache (default for reproduction); `off` means no LLM at all. |
| `LLM_BASE_URL`, `LLM_API_KEY` | Server address and key (local servers accept any key). |
| `LLM_MODEL` | The server's own model name (differs between LM Studio and `llama serve`). |
| `LLM_MODEL_TAG` | **Logical** name used in cache keys, the same on both machines (e.g. `gemma-4-e4b-<quant>`). |
| `LLM_TEMPERATURE`, `LLM_MAX_TOKENS` | Sampling settings. |
| `LLM_SEED` | Default seed when `run` is called without one. |

* **Cache key** = SHA256 of canonical JSON of {`LLM_MODEL_TAG`, system prompt, user prompt, response schema, temperature, max tokens, seed}. The server address and server model name are **not** in the key. Only machine K writes to `cache/llm_replay.jsonl` (committed). A miss in replay mode is `E_REPLAY_MISS`.
* Prompts live in `app/prompts/*.md`. Their hash goes into `metadata.llm.prompt_hash`.
* Record in every live run's metadata: backend and build (K: `llama serve`, version 0.6.0-dev build 11429; S: LM Studio version), launch flags, GGUF SHA256, quantisation, context size, sampling settings, seed. Hash only the main `.gguf` file.
* **Not yet verified** (Day 1): that `llama serve` exposes `/v1/chat/completions` with JSON-schema output. If it does not, the client falls back to "prompt for JSON, validate, retry". Callers see no difference. Freeze the llama build after Day 1 (`llama update` is banned).

---

## 9. Testing contract

### 9.1 What the tests does and does not call

The tests calls `run(...)` directly (not via the API). It builds each follow-up input from the source input by one named transformation. It never reaches into agent internals; everything it asserts is a field in section 6.

### 9.2 Binding table (what each MR may assert; full prose goes in `MR_SPEC.md`)

"Skip when" is part of the MR's input subdomain. It is written only in terms of report fields, so it can be checked automatically. Both the source and the follow-up are checked.

| MR | Family | Transformation (source → follow-up) | Assert (comparator) | Do **not** assert | Skip when |
|---|---|---|---|---|---|
| 1 | Invariance | Shuffle rows (seeded permutation) | Whole report except `trace`, `diagnostics`, `metadata` (**bit-exact floats**) | — | never |
| 2 | Invariance | `price` and `price_band` divided by 100,000; `price_unit = "lakh"` | counts, flags, `coverage_score`, `direction`: EXACT. `median_price`, `median_price_per_sqft`, `summary.start/end` equal source ÷ 100,000 (REL_TOL). `pct_change`, `change_pct` equal (ABS). | `price_unit` string | flag margin: any `|pct| − ANOMALY_PCT| < 1e-9` |
| 3a | Invariance | Every row duplicated, **new** `listing_id`s (`<id>_dup`) | counts ×2 (EXACT); medians, `pct_change`, `summary.start/end/change_pct`, flags equal | `low_sample` | any `ALL` month with `n_in_bucket` ∈ {3, 4} (doubling would cross `MIN_BUCKET_N`); `L2_attempts > 0` |
| 3b | Invariance | Every row duplicated, **same** `listing_id`s | same as 3a | same | same. Violation here = the application logic dedups, which breaks D3/I-NODEDUPE. |
| 4 | Monotonic | +X added to `price` of every row in one window month m (X ∈ {250,000; 1,000,000}) | month m: `median_price` = source + X (REL_TOL), counts EXACT, for every region. Every month ≠ m: **all** record fields equal. No month's `median_price` decreases. | month m `median_price_per_sqft`; `pct_change` and flags of months m and m+1; `summary`; | `price_band` is set (rows could cross the band); `n_in_bucket(m)` < `MIN_BUCKET_N` for `ALL` |
| 5 | Monotonic | `price_band` widened by δ ∈ {0.1, 0.3} of its width on each side | `listing_count` follow-up ≥ source for every (month, region) | medians | `price_band` null; `L2_attempts > 0` in either run |
| 6 | Monotonic | `localities` L → proper non-empty subset S ⊂ L (L may be null = all) | `ALL.listing_count(S) ≤ ALL.listing_count(L)` per month. Locality records for l ∈ S equal in both runs (EXACT/REL). | `coverage_score` | \|L\| < 2; `L2_attempts > 0` in either run |
| 7 | Directional | `window_end` + 1 month | The 11 overlapping months: all record fields equal for every region. `pct_change` and flags compared only for the 10 overlap months after the first one (the follow-up's first month has no predecessor). | `coverage_score`, `summary`, `n_rows` | `L2_attempts > 0` in either run; `window_end + 1` beyond the snapshot |
| 8 | Directional | `price` and `price_band` × k, k ∈ {2, 4, 10} | counts, flags, `coverage_score`, `direction`: EXACT. Medians and `summary.start/end` equal source × k (REL_TOL). `pct_change`, `change_pct` equal (ABS). | — | flag margin as in MR2 |
| 9 | Invariance | Paraphrase of the sentence (≥ 4 phrasings per base, incl. "last year") | **First** `effective_criteria` EXACT (set semantics). Then `records`, `summary`, `anomaly_flags`, `coverage_score` EXACT. | `diagnostics`, `trace` | `LLM_MODE = off` |
| 10 | Monotonic (additive) | `bhk = null` (or set B) → one run per value b ∈ B | Σ over b of `listing_count` = source `listing_count`, per (month, region) (EXACT) | medians | `L2_attempts > 0` in any run; soft filters set |
| X1 | (stretch) Invariance | `force_topology` flipped | Whole report except `metadata.topology`, `metadata.n_scanners` | — | never |

Notes:
* **MR1's bit-exact rule** is deliberate: sorted-value medians must not depend on row order at all. MR3 medians should also come out bit-exact; if they differ by more than 1 ulp, inspect before concluding anything.
* The "Skip when" rows with `L2_attempts > 0` are the probe for loop interference. The headline table reports **conditioned** results (skips applied). Also report, in a second column, the **unconditioned** violation rate for MRs 3, 5, 6, 7, 10. A large gap is itself evidence (it points to L2 or the coverage gate, not to the MR being wrong).
* MR7 is labelled Directional because the assignment table does; in substance it is an invariance on the overlap. Say so in the MR spec.
* A violation must name its field. The log row is {MR, base id, seed, field, source value, follow-up value}.

### 9.3 Base inputs

* One **base input** = one distinct `Criteria` (canonical JSON). Distinct bases are the unit for counting, confidence intervals and independence. The 3 seeds on one base are not independent; say so in threats to validity.
* Generator: seeded by `GEN_SEED`; for each draw it samples a `window_end` uniformly over the 123 valid ends, then localities (a random subset of those with ≥ 30 sales in that window), BHK (null half the time, else 1–2 values with ≥ 10 sales), and a price band (null half the time, else window price quantiles q_lo ∈ [0, 0.4], q_hi ∈ [0.6, 1]).
* **Eligibility** (decided on the unmodified snapshot, before any transformation): *broad stratum* = ≥ 60 matching rows; *thin stratum* = 20–59 matching rows **and** a price band set (these exercise L2). Target mix 80 % broad, 20 % thin. In a 3,000-draw prototype, 78 % of draws were broad and 16 % were 20–59 rows.
* Counts: Mode A ≥ 100 bases per MR (all 10 MRs, `LLM_MODE=off`). Mode B ≥ 30 bases (50 target) per MR for MR 9, plus MR 1 and 3 in AI mode.
* Each MR also needs its own parameters drawn from the same seeded stream (X, δ, k, subset S, month m) so that the base list and the parameters can be regenerated from `GEN_SEED`. Store them in the result file.

### 9.4 Seeds and statistics

* **Mode A** (`LLM_MODE=off`): the application logic is deterministic by construction. Run each base once with `seed = 0`, and run the determinism self-test (same input twice → identical bytes, I-DET) on every base. State in the report that k = 3 seeds add nothing here.
* **Mode B** (`LLM_MODE=live` on K's machine, then replayed): each base runs under all seeds in `SEEDS`; the source and follow-up of a pair use the same seed (D9). A **base violates** if **any** seed pair violates (any-seed rule). Also report the per-pair rate as a second number.
* **Violation rate** = violating bases / bases. **95 % interval:** Wilson score interval (z = 1.96). When the count is 0 or equals n, use Clopper–Pearson. For 0 violations in n bases the two-sided upper bound is `1 − 0.025^(1/n)`: n = 30 → 11.6 %, n = 100 → 3.6 %.
* Report per MR: seed list, base count, violation count and rate, CI, and the sample sizes of the skipped bases (a skip is not a pass).

### 9.5 Oracle, logs, process

* `tests/oracle.py` is an independent plain-pandas implementation of every formula in 6.2–6.3. It must not import application logic code. Check it first against the golden vectors (Appendix A), then use it to check the application logic on every base: any mismatch is a bug in the application logic, the oracle, or the contract; fix before running MRs.
* **Pre-registered predictions** (write these in `NOTEBOOK.md` before the first full run): most likely top violations are MR3 (ID dedup or the `MIN_BUCKET_N` gate), MR7 (window-wide state: coverage, first-month predecessor, L2), and MR8/MR2 (an absolute threshold). If reality differs, record it.
* **Diagnosis protocol** for the 3 most-violated MRs: (1) shrink to a minimal case, (2) diff the traces and `loop_counters` between source and follow-up, (3) rerun with `loops_enabled = false`, (4) check by hand against the oracle, (5) classify as agent fault / data artifact / ill-conceived MR / tests bug, with the evidence.
* **Process:** log every violation to `results/violations.csv` and tag `v0-results` before fixing anything. Keep before/after rates. Final headline run is tagged `final-results`.

---

## 10. API contract (S)

All three endpoints return JSON; CORS is on. Domain errors come back as HTTP 200 with a report whose `status` is `"error"`; HTTP 500 means a crash (a bug).

| Endpoint | Returns |
|---|---|
| `GET /api/meta` | `localities`, `bhk_values`, `sale_conds`, `first_month`, `latest_month`, `window_end_min` (2004-12), `window_end_max` (2015-02), `default_window_end`, `sales_per_month` {`YYYY-MM`: int}, `localities_active_by_month` {`YYYY-MM`: [names]}, `snapshot_sha256`, `constants` (section 3), `partial_months` |
| `POST /api/run` | Body `{ "criteria": Criteria }` or `{ "nl_query": str }`, plus optional `seed`, `options`. Returns a `TrendReport`. |
| `GET /api/health` | `{ "status": "ok", "llm_mode", "snapshot_sha256", "application logic_version", "contract_version" }` |

**UI rule:** the UI displays application logic numbers and does no calculations (no medians, no percentages, no unit conversion). Rounding and "lakh/crore" labels are display formatting only. Build the UI first against a hand-written `example_response.json` that obeys section 6, then switch the API address. `localities_active_by_month` exists so the UI can grey out localities with no sales in the chosen window (F2, F3).

---

## 11. Repository and reproduction contract

```
CONTRACT.md  NOTEBOOK.md  AI_USE.md  README.md  .env.example
data/raw/Chennai_Housing_Sale.csv   data/chennai_snapshot.csv   data/SNAPSHOT.sha256
scripts/freeze_snapshot.py          scripts/golden_vectors.py
app/   contract.py (constants + pydantic models), orchestrator.py, agents/, llm_client.py, prompts/   (S; K owns llm_client.py)
api/  ui/                                                                                              (S)
tests/  oracle.py, generator.py, mrs/, stats.py, run.py, reproduce.py                                (K)
cache/llm_replay.jsonl     results/ (violations.csv, headline_table.md, run_manifest.json)
docs/ design_note, MR_SPEC.md, report
```

**One-command reproduction:** `python -m tests.reproduce` rebuilds `results/headline_table.md` from the frozen snapshot, `GEN_SEED`, `SEEDS` and `LLM_MODE=replay`. It must not need a GPU or a network. `run_manifest.json` records: snapshot hash, contract version, git commit, seeds, base counts, library versions, LLM metadata (section 8). The command must fail loudly on a snapshot hash mismatch or a replay-cache miss. State in the report that a live (non-replay) run may drift.

---

## 12. Open items and changelog

**Open items:**
1. Both confirm D1–D10, or change them (S, K — today, before Gate 1).
2. Verify that `llama serve` exposes an OpenAI-compatible endpoint with JSON-schema output; record version, flags, GGUF hash; confirm the same GGUF on both machines (K, Day 1).
3. Check the Kaggle licence wording and add the citation (K, Day 1).
4. Project name is undecided (not needed by the contract).
5. Write `example_response.json` from section 6 using the golden numbers (S, Day 1).
6. Redraw the control-flow graph with L1 and L2 marked as cycles and update the design note per section 2 (S, Day 1).

| Version | Date | Who | Change |
|---|---|---|---|
| 1.0.0 | 2026-10-10 | draft | First full contract, built from the dataset verification. |
| | | S: ☐ agreed | |
| | | K: ☐ agreed | |

---

## Appendix A. Golden vectors (must be reproduced by application logic and oracle)

Generated by `python scripts/golden_vectors.py data/chennai_snapshot.csv 2015-02 2011-12`. These are for criteria with **no filters** (all localities), `price_unit = "inr"`, loops irrelevant (coverage passes). Tolerance: REL_TOL.

**A1. `window_end = 2015-02`, `ALL` region** (338 rows, `coverage_score` = 1.0, `topology` = parallel, 12 of 12 months ≥ 5 sales)

| month | listing_count | median_price | median_price_per_sqft | pct_change_price_per_sqft |
|---|---|---|---|---|
| 2014-03 | 24 | 12440755.0 | 8070.312067 | null |
| 2014-04 | 22 | 12020615.0 | 8630.727643 | 0.06944162409 |
| 2014-05 | 34 | 12308475.0 | 8650.144189 | 0.002249699676 |
| 2014-06 | 31 | 11216030.0 | 8628.894737 | −0.002456543058 |
| 2014-07 | 31 | 12026900.0 | 8656.234991 | 0.00316845383 |
| 2014-08 | 28 | 12691755.0 | 9480.940645 | 0.09527302047 |
| 2014-09 | 25 | 12368280.0 | 8885.390295 | −0.06281553402 |
| 2014-10 | 25 | 10676410.0 | 9095.651659 | 0.02366371723 |
| 2014-11 | 35 | 12123360.0 | 9110.533333 | 0.001636130662 |
| 2014-12 | 32 | 11722730.0 | 10459.20943 | **0.148034813** |
| 2015-01 | 28 | 11950775.0 | 8919.117162 | **−0.1472474836** |
| 2015-02 | 23 | 11412420.0 | 8508.576779 | −0.04602926223 |

* `anomaly_flags`: `price_jump` at 2014-12 (+0.148035) and at 2015-01 (−0.147247). No `count_drop`.
* `summary.price`: start 12303430, end 11618510, change −5.566902888 %, `down`.
* `summary.price_per_sqft`: start 8491.884579, end 8945, change +5.335864105 %, `up`.
* Per locality in this window only Anna Nagar (96 rows), Chrompet (186) and T Nagar (56) have sales; the other 4 localities still appear in `records` with `listing_count = 0` and null medians (I-DENSE).

**A2. `window_end = 2011-12`, `ALL` region** (1,300 rows, `coverage_score` = 1.0, 7 localities active): no flags. `summary.price`: start 10481780, end 9493200, −9.431413367 %, `down`. `summary.price_per_sqft`: start 7855.461839, end 7478.921224, −4.793360633 %, `down`.

**A3. L2 example:** the Adyar / 1 BHK / ₹70–90 lakh / 2010-12 query in section 7.4 (rows 38 → 49 → 71; covered months 3 → 6 → 9; `L2_attempts` = 2).

## Appendix B. Report shape (abbreviated; `example_response.json` is the full version)

```json
{
  "status": "ok", "error": null,
  "criteria_in":        {"localities": null, "window_end": "2015-02", "bhk": null, "price_band": null,
                         "sqft_range": null, "sale_cond": null, "price_unit": "inr"},
  "effective_criteria": {"...": "same shape; shows L1 repairs and L2 widening"},
  "price_unit": "inr",
  "records": [
    {"month": "2014-03", "region_key": "ALL", "listing_count": 24, "n_in_bucket": 24,
     "median_price": 12440755.0, "median_price_per_sqft": 8070.312067, "low_sample": false,
     "pct_change_price_per_sqft": null},
    {"month": "2014-03", "region_key": "Adyar", "listing_count": 0, "n_in_bucket": 0,
     "median_price": null, "median_price_per_sqft": null, "low_sample": true,
     "pct_change_price_per_sqft": null}
  ],
  "summary": {"n_rows": 338,
              "price": {"start": 12303430.0, "end": 11618510.0, "change_pct": -5.566902888, "direction": "down"},
              "price_per_sqft": {"start": 8491.884579, "end": 8945.0, "change_pct": 5.335864105, "direction": "up"}},
  "coverage_score": 1.0,
  "anomaly_flags": [{"month": "2014-12", "region_key": "ALL", "kind": "price_jump",
                     "value": 0.148034813, "threshold": 0.12, "reason": "median price per sqft rose 14.8% vs 2014-11"}],
  "diagnostics": [{"month": "2014-12", "text": "...", "source": "template"}],
  "trace": [{"i": 0, "agent": "planner", "kind": "decision", "loop": null,
             "msg": "topology=parallel (7 localities >= 3)", "data": {}}],
  "metadata": {"contract_version": "1.0.0", "topology": "parallel", "n_scanners": 7, "seed": 0,
               "loop_counters": {"L1_repairs": 0, "L2_attempts": 0}, "partial_last_month": true,
               "snapshot_sha256": "18487b6f...", "llm_mode": "off", "llm": null}
}
```
