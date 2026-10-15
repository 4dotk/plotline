# GLOBAL CONTRACT — Chennai Housing-Trends Application (v1.1.2)

The single source of truth for project requirements. The application logic, API, UI, test suite, report and every subcontract must comply with this file. If code or a subcontract disagrees with it, that is a defect: fix the code or subcontract, not this file, unless the team formally approves a global change.

**Words:** MUST = no exceptions. SHOULD = do it unless you write down why not. "Application" = the orchestrator plus its agents, called as a Python function. "Test suite" = the metamorphic test code that calls it.

**Change rule:** nobody edits sections 3 to 9 alone. Add a changelog line (section 12), the whole team agrees, bump the version, tell the team. After the `v0-results` tag, a change needs a changelog line that says what was wrong (the report must explain every change).

## 1. Structure and how to read it

This file is about 8k tokens (estimated): too big to load with code into an 8k context. A coding agent therefore never loads it whole: it reads `contracts/agents/_common.md` plus its own agent file (about 1.5–2k tokens). Detail lives in subcontracts; they add detail and MUST NOT contradict this file; if they do, this file wins.

| File | Read it when you work on |
|---|---|
| `contracts/data.md` | data source, cleaning rules, snapshot, data boundaries |
| `contracts/llm.md` | model config, modes, cache, validation, retries, fallbacks |
| `contracts/testing.md` | oracle, MRs, skip rules, base inputs, statistics, result logging |
| `contracts/golden.md` | golden vectors (Appendix A), report example (Appendix B) |
| `contracts/agents/_common.md` + one `contracts/agents/<X>_<name>.md` | **one agent: always these two files and nothing else** |
| `contracts/agents/_review.md` | humans only (open clarifications, traceability) |

`app/contract.py` (constants + pydantic models) MUST match sections 3, 5 and 6.

## 2. Decisions made in this contract

| ID | Decision | Alternative you could pick |
|---|---|---|
| D1 | **Real data only, no synthetic snapshot.** The seeded generator must provide enough eligible cases. | Add a synthetic snapshot. |
| D2 | **Default `window_end` = latest month (2015-02)**; "last year" resolves to it; the partial month is flagged. Test base inputs never use the default (9.3). | Default to 2011-12 (all 7 localities). Change one constant. |
| D3 | **The application never deduplicates.** One row = one sale. | Dedup by `listing_id`; breaks MR3b. |
| D4 | **Coverage and L2 use the all-locality (`ALL`) series only** (12 cells). | Per-cell coverage fires L2 almost always. |
| D5 | **Anomalies are detected on the `ALL` series** (median ₹/sqft jump, listing-count drop). All thresholds are ratios. | Per-locality anomalies are too noisy. |
| D6 | **Prices carry a unit:** `median_price` plus `price_unit` ∈ {`inr`, `lakh`}. | `_inr` in the name; breaks MR2. |
| D7 | **L2 widens only "soft" filters** (price band, sqft range, sale condition). Locality, BHK, window are "hard". | Widen everything; silently changes the request. |
| D8 | **The one row with no bedroom count is dropped at freeze** (7,109 → 7,108). | Keep with `bhk = null`; breaks MR10. |
| D9 | **Same-seed pairs:** a source run and its follow-up use the same seed. | Independent seeds. |
| D10 | **Replay cache is keyed on a logical model tag** (`LLM_MODEL_TAG`), not the server's model name. | — |
| D11 | **The model has three jobs and never makes a number:** (a) Planner: sentence → `Criteria`; (b) Validator: choose `widen` or `stop` in L2; (c) Diagnostic: text. With `LLM_MODE=off`, (b) is the rule `widen`. | Keep the model in two places only (v1.0.0). |


---

## 3. Constants (one file: `app/contract.py`)

No other file may contain these numbers. Everything else imports them.

| Name | Value | Meaning |
|---|---|---|
| `WINDOW_MONTHS` | 12 | Window length. Not user-changeable. |
| `DEFAULT_WINDOW_END` | `"latest"` → 2015-02 | See D2. |
| `MIN_BUCKET_N` | 5 | A bucket with fewer sales is `low_sample`. |
| `COVERAGE_MIN_MONTHS` | 9 | Need ≥ 9 of 12 months with ≥ `MIN_BUCKET_N` sales. Compared as an **integer**. |
| `ANOMALY_PCT` | 0.12 | Flag a month if \|month-on-month change of median ₹/sqft\| > 0.12 (about 23 % of month pairs on the unfiltered series). |
| `COUNT_DROP` | 0.5 | Flag a month if its count ≤ 0.5 × the previous month's count. |
| `FLAT_BAND_PCT` | 1.0 | Summary direction is `flat` if \|change\| ≤ 1 %. |
| `L1_CAP` | 2 | Maximum parameter repairs. |
| `L2_CAP` | 3 | Maximum coverage retries. |
| `L2_WIDEN` | (0.20, 0.50, "drop") | Retry 1 widens each soft range by 20 % of its width on each side, retry 2 by 50 %, retry 3 removes soft filters. Always from the **original** value. |
| `TOPOLOGY_PARALLEL_MIN_LOCALITIES` | 3 | ≥ 3 localities (or `null` = all) → parallel scanners, else one consolidated scanner. |
| `REL_TOL` / `ABS_TOL` / `ABS_TOL_PCT` | 1e-9 / 1e-9 / 1e-7 | Tolerances: relative; absolute for fractions; absolute for values in percent. |
| `SEEDS` | (101, 202, 303) | The k = 3 recorded seeds. |
| `GEN_SEED` | 42 | Seed for the base-input generator. |

---

## 4. Data contract (detail: `contracts/data.md`)

### 4.1 Files

`data/raw/Chennai_Housing_Sale.csv` (original Kaggle file, committed unchanged; hash in `data.md`) · `data/chennai_snapshot.csv` (**the frozen snapshot, the only data the application and tests read**; 7,108 rows; SHA256 `18487b6ff164507f254c7bca38f13be786523b1e3fec03dd457bffa866cb6209`) · `data/SNAPSHOT.sha256` (that hash on one line; the application MUST recompute and compare it at start-up and refuse to run on a mismatch: `E_SNAPSHOT_HASH`). `scripts/freeze_snapshot.py` MUST print exactly the snapshot hash. Source: Kaggle "Chennai Housing Sales Price"; check its licence and cite it.

### 4.2 Cleaning

Rules R1–R5 (spelling fixes, drop the one row with no bedrooms, ISO dates, keep 7 columns) are applied **once, by the freeze script, never by the application**. The rule table is in `data.md`.

### 4.3 Snapshot columns (the dataframe the application receives)

`listing_id` (str, e.g. `P00001`) · `locality` (str, one of the 7 canonical names) · `sqft` (int) · `sale_date` (str `YYYY-MM-DD`) · `bhk` (int 1–4) · `sale_cond` (str: `AbNormal`, `AdjLand`, `Family`, `Normal Sale`, `Partial`) · `price` (int or float, **in `criteria.price_unit`**; INR in the snapshot). Canonical localities (sorted): `Adyar, Anna Nagar, Chrompet, KK Nagar, Karapakkam, T Nagar, Velachery`.

### 4.4 Time rules

* A sale belongs to the month `sale_date[:7]`. No time zones.
* The window is the 12 calendar months ending at `window_end`, inclusive.
* Valid `window_end`: **2004-12 … 2015-02** (123 values), read from the data, not hard-coded. `GET /api/meta` publishes them.
* The application MUST NOT read the system clock. "Last year" always resolves to 2015-02, never to today (I-CLOCK).
* 2004-01 and 2015-02 are partial months. `metadata.partial_last_month = true` when the window ends at the latest month. Report it, do not "fix" it.

---

## 5. Input contract

### 5.1 Entry point

```python
run(query: Criteria | str, listings_df: pandas.DataFrame, seed: int = 0,
    options: RunOptions = RunOptions()) -> TrendReport
```

* `query` is a `Criteria` (structured mode) or a sentence (AI mode, through the Planner).
* `listings_df` has exactly the columns of 4.3. The application MUST NOT read files, the network or the clock inside agents, and MUST NOT modify `listings_df` or the `Criteria` it is given (I-PURE). Tests build every transformed dataset as a new dataframe.
* `seed` only reaches the LLM client. With `LLM_MODE=off` it changes nothing.

### 5.2 `Criteria`

| Field | Type | Default | Rule |
|---|---|---|---|
| `localities` | list[str] or null | null = all 7 | Canonical names. Unknown names go to L1. |
| `window_end` | `"YYYY-MM"` | latest month | Valid range in 4.4. Outside it goes to L1 (clamp). |
| `bhk` | list[int] or null | null = any | Values 1–4. |
| `price_band` | [lo, hi] or null | null | **Soft.** Inclusive, in `price_unit`. `lo > hi` goes to L1 (swap). |
| `sqft_range` | [lo, hi] or null | null | **Soft.** Inclusive. |
| `sale_cond` | list[str] or null | null = any | **Soft.** Canonical names. |
| `price_unit` | `"inr"` or `"lakh"` | `"inr"` | A label only. The application does **no** unit conversion. 1 lakh = 100,000 INR, 1 crore = 10,000,000 INR (used by the sentence parser only). |

List filters are compared as **sets**. Two `Criteria` are "the same base input" when their canonical JSON is equal (keys sorted, lists sorted, numbers as written).

### 5.3 `RunOptions` (test hooks; defaults reproduce normal behaviour)

* `loops_enabled` (default true): `false` turns L1 and L2 off. Invalid criteria then return `E_INVALID_CRITERIA`; low coverage logs "L2 disabled" and continues.
* `force_topology` (default null): `"parallel"` or `"consolidated"` overrides the Planner. Tests only.

### 5.4 AI mode (sentence in)

The Planner turns a sentence into a `Criteria` and nothing else. "Last year", "past year", "last 12 months", "this year" = `window_end` is the latest month; a named month sets that `window_end`; money words become INR. If model output is unparseable the rule-based parser runs; if that fails: `E_NL_UNPARSEABLE`.

---

## 6. Output contract

### 6.1 The 12-month trend

For each month of the window and each region: **listing count, median price, median price per sqft**. For the whole window: **first-3-months vs last-3-months change** in median price and median ₹/sqft. Plus a **coverage score** and **anomaly flags**. Nothing else is a trend statistic.

### 6.2 `TrendReport`

Fields: `status` (`"ok"` or `"error"`) · `error` (null or {`code`, `message`}) · `criteria_in` (the request as received) · `effective_criteria` (after L1 repairs and L2 widening: what was actually computed) · `price_unit` (copy of `effective_criteria.price_unit`) · `records` (list of `TrendRecord`, dense grid below) · `summary` (`Summary` or null) · `coverage_score` (float) · `anomaly_flags` (list of `AnomalyFlag`) · `diagnostics` (list of {`month`, `text`, `source`}; model or template text, UI only) · `trace` (7.4) · `metadata` (6.4).

Which comparator tests use for each field (EXACT, REL_TOL, ABS_TOL, bit-exact; `diagnostics`, `trace`, `metadata` ignored by default) is in `testing.md` §3 and §5.

**Dense grid rule (I-DENSE).** `records` has one record for every pair (month in window, region), including zero-sale pairs. Regions = `ALL` plus each locality in `effective_criteria.localities` (all 7 if null). The key set depends **only** on `effective_criteria`, never on the data. Order: month ascending, `ALL` first, then localities alphabetically. **Consumers MUST NOT rely on order**; tests compare by key (`month`, `region_key`).

**`TrendRecord`**

| Field | Type | Definition |
|---|---|---|
| `month` | `"YYYY-MM"` | key |
| `region_key` | str | key: `"ALL"` or a canonical locality. `ALL` pools all rows that match the filters. |
| `listing_count` | int | Rows matching all filters in this month and region. |
| `n_in_bucket` | int | Rows of those with finite `price` > 0 and `sqft` > 0 (used for medians). ≤ `listing_count`. |
| `median_price` | float or null | Median of `price` over the `n_in_bucket` rows; even count → mean of the two middle values; null if `n_in_bucket` = 0. |
| `median_price_per_sqft` | float or null | Median of per-row `price / sqft` (float64). null if `n_in_bucket` = 0. |
| `low_sample` | bool | `n_in_bucket < MIN_BUCKET_N`. |
| `pct_change_price_per_sqft` | float or null | **`ALL` only.** `median_ppsf[t] / median_ppsf[t−1] − 1` when both months have `n_in_bucket ≥ MIN_BUCKET_N`, else null. First month always null. |

**`Summary`** (always the `ALL` region): `n_rows` = rows matching the filters inside the window. `price` and `price_per_sqft` are each null or {`start`, `end`, `change_pct`, `direction`}; both are null if the pooled first-3-months or last-3-months set has fewer than `MIN_BUCKET_N` rows. `start` / `end` = median of that statistic over all rows of the **first 3** / **last 3** months, pooled (not an average of monthly medians). `change_pct = (end / start − 1) × 100` (percent). `direction` = `up` if `change_pct` > `FLAT_BAND_PCT`, `down` if < −`FLAT_BAND_PCT`, else `flat`.

### 6.3 Formulas the test oracle re-implements

* **`coverage_score`** = (number of the 12 months whose `ALL` record has `n_in_bucket ≥ MIN_BUCKET_N`) / 12. The loop test is on the integer count: need `≥ COVERAGE_MIN_MONTHS`.
* **`anomaly_flags`**, all on the `ALL` series, each `{month, region_key: "ALL", kind, value, threshold, reason}`:
  * `price_jump` at t if `pct_change_price_per_sqft[t]` is not null and `|…| > ANOMALY_PCT`. `value` = that fraction.
  * `count_drop` at t if month t−1 has `n_in_bucket ≥ MIN_BUCKET_N` and `listing_count[t] ≤ COUNT_DROP × listing_count[t−1]`. `value` = `listing_count[t] / listing_count[t−1]`.
  * The first month of a window is never flagged.
* **Medians:** numpy `median` semantics on sorted values. **No rounding** anywhere in the application (rounding is UI only).

### 6.4 `metadata`

`contract_version`, `logic_version` (git short hash), `snapshot_sha256`, `seed`, `llm_mode`, `topology` (`parallel` | `consolidated`), `n_scanners`, `loops_enabled`, `loop_counters` = {`L1_repairs`, `L2_attempts`}, `partial_last_month`, `llm` (null, or {`backend`, `build`, `launch_flags`, `gguf_sha256`, `quant`, `ctx`, `temperature`, `seed`, `prompt_hash`}).

### 6.5 Error codes

A domain error is **a report with `status = "error"`, never an exception** (I-ERR). Crashes are bugs.

| Code | When |
|---|---|
| `E_INVALID_CRITERIA` | Still invalid after `L1_CAP` repairs, or `loops_enabled = false`. `message` names the field. |
| `E_NL_UNPARSEABLE` | AI mode: model and rule parser both failed. |
| `E_LLM_OFF` | AI mode requested with `LLM_MODE=off`. |
| `E_REPLAY_MISS` | `LLM_MODE=replay` and the request is not in the cache. Never a silent live call. |
| `E_SCHEMA` | `listings_df` is missing a column of 4.3. |
| `E_SNAPSHOT_HASH` | Snapshot file does not match `data/SNAPSHOT.sha256`. |

On an error: `records = []`, `summary = null`, `coverage_score = 0`, `trace` still filled.

---

## 7. Behaviour contract

### 7.1 Agents: what kind each is, and who may do what

| Agent | Kind | One-line job | May use the model? | May change |
|---|---|---|---|---|
| A Query Planner | decision-maker | Turns the request into valid `Criteria`; picks scanner topology; repairs bad criteria (L1). | AI mode only: sentence → `Criteria` | `effective_criteria`, topology |
| B Scanners | worker | Return the rows matching `effective_criteria`; one scanner per locality (parallel) or one for all (consolidated). | No | Row set |
| C Result Aggregator | worker | Validates criteria and rows; builds the dense grid of buckets, medians, counts. | No | `records` |
| D Coverage Validator | decision-maker | Computes `coverage_score`; decides `widen` or `stop` (L2). | Yes: `widen` or `stop` only; the rule is `widen` when the model is off | Triggers L2 |
| E Anomaly Detector | worker | Computes `pct_change`, `anomaly_flags`, `summary`. | No | Flags, summary |
| G Diagnostic | text writer | Writes a short plain-language reason for each flag. | Yes (template if off) | `diagnostics` only |
| F Reporter | worker | Assembles the `TrendReport`. | No | Nothing numeric |

A **worker** is a plain function of its inputs. The report and design note say plainly which agents are workers and which decide.

### 7.2 Invariants (every run, every mode; the tests check I-DET, I-PURE, I-DENSE for free)

| ID | Rule |
|---|---|
| I-DET | With `LLM_MODE` ∈ {off, replay}, the same (`query`, `listings_df`, `seed`, `options`) gives a **byte-identical JSON** report. No wall-clock timing inside the report. |
| I-ORDER | Output does not depend on input row order. Medians use sorted values, never order-dependent running sums. |
| I-TOPO | Output does not depend on topology; topology appears only in `metadata`. |
| I-LLM | The model can change only (a) the `Criteria` the Planner produces in AI mode, (b) whether L2 widens or stops, (c) the text in `diagnostics`. **Every number comes from code**; (b) changes which criteria are computed, never how. |
| I-UNIT | No absolute rupee, sqft or count constants except section 3. Scaling prices must not change any flag. |
| I-NODEDUPE | Rows are counted; duplicate rows and duplicate `listing_id`s count. |
| I-PURE | Never modify `listings_df` or the `Criteria` given. |
| I-DENSE | The key set of `records` depends only on `effective_criteria`. |
| I-CLOCK | No system clock, no random numbers outside the LLM client. |
| I-CAP | Each loop has a hard cap. Every loop firing writes exactly one trace event; `loop_counters` equals the number of such events. |
| I-ERR | Domain problems return `status = "error"`; the application does not raise. |
| I-FLOAT | No rounding, no float formatting, in the report. JSON uses the shortest round-trip form. |

### 7.3 Control flow

```
A Planner ══▶ B Scanners ──▶ C Aggregator ──▶ D Validator ──▶ E Anomaly ──▶ G Diagnostic ──▶ F Reporter
   ▲   (⇒ A's topology         ▲      │              │
   │    changes what B does)   └──────┼──────────────┘ L2: coverage low → D decides widen/stop; widen → rescan (cap 3)
   └──────── L1: invalid criteria, repair and restart (cap 2) ──┘ (C sends work back to A)
```

* **L1 Parameter Repair (C → A), feedback loop.** C finds invalid criteria and sends them to A with a code; A repairs and the pipeline restarts from B. Cap `L1_CAP`. All repairable issues found in one pass count as **one** repair.

  Repairs: `band_inverted` → swap; `locality_unknown` → closest canonical name (difflib, cutoff 0.8), no match → cannot repair; `window_out_of_range` → clamp to the nearest valid `window_end`; `bhk_out_of_range` → drop the bad value, empty → cannot repair (table in `agents/_common.md`).
  Cannot repair, or cap reached → `E_INVALID_CRITERIA`.
* **L2 Coverage Retry (D → B), conditional/iterative step.** When (months with `n_in_bucket ≥ MIN_BUCKET_N`) < `COVERAGE_MIN_MONTHS`, loops are on, soft filters exist and attempts < `L2_CAP`, D **decides**:
  * `LLM_MODE=off`: the rule is `widen`. Live or replay: the model chooses `widen` or `stop`. Its prompt holds counts and filter names only, **never a price or sqft value**, so scaling or shuffling the data leaves the prompt unchanged.
  * `widen`: apply the next `L2_WIDEN` step to the **original** soft filters (`[lo − f·(hi−lo), hi + f·(hi−lo)]`, lower end floored at 0; step 3 removes `price_band`, `sqft_range`, `sale_cond`), rescan, re-aggregate, re-check. `effective_criteria` always shows the widened values.
  * `stop`: continue with the low `coverage_score`. A `decision` trace event, **not** a loop firing.
  * Malformed model output after retries → the rule (`widen`). Stop at the cap and continue with the low score.
  * No soft filters: write `L2 skipped: nothing to widen` and continue (not an attempt).
* **Dependency (A ⇒ B).** The topology A chooses changes what B *does* (how many scanners, how the work is split), not just the data it gets. I-TOPO says the numbers must not change.
* **L3** (Anomaly → Scanners) is **stretch and not in this contract.** Do not draw it.

### 7.4 Trace

`trace` is a list of `{i, agent, kind, loop, msg, data}`. `i` counts from 0; `agent` ∈ `planner|scanner|aggregator|validator|anomaly|diagnostic|reporter`; `kind` ∈ `step|decision|loop|warning|error`; `loop` is `L1`, `L2` or null. Every loop firing MUST be a `kind = "loop"` event with these exact templates (the report's execution trace is copied from here):

| Loop | `msg` template | `data` keys |
|---|---|---|
| L1 | `L1 fired: {issue}; {before} -> {after}; repair {n} of 2` | `issue`, `before`, `after`, `repair_no`, `cap` |
| L2 | `L2 fired: coverage {months}/12 below {need}/12; {action}; attempt {n} of 3` | `coverage_months`, `need_months`, `action`, `factor`, `attempt`, `cap`, `effective_price_band`, `decided_by` (`"rule"` or `"llm"`) |

The worked L2 example (Adyar, 1 BHK, ₹70–90 lakh, 2010-12: rows 38 → 49 → 71, covered months 3 → 6 → 9) is in `golden.md` A3. It is the first test of L2.

---

## 8. LLM contract (detail: `contracts/llm.md`)

* Only **one module** (`app/llm_client.py`) may talk to a model. Three uses (D11): Planner (AI mode), Validator (L2 decision), Diagnostic. Temperature 0; JSON checked with pydantic; malformed output → one `warning` trace event, up to 2 retries, then the fallback (rule-based parser / the rule `widen` / the template), logged.
* `LLM_MODE`: `live`, `replay` (default for reproduction, answers from the committed cache) or `off`. Settings come from `.env` only; commit `.env.example`, never `.env`.
* **Thinking** is fixed per use and sent with every request (`chat_template_kwargs.enable_thinking`): on for the Planner, off for the Validator and Diagnostic.
* **Cache key** = SHA256 of canonical JSON of {`LLM_MODEL_TAG`, system prompt, user prompt, response schema, temperature, max tokens, seed, thinking}; server address and server model name are not in it (D10). Only the canonical machine writes `cache/llm_replay.jsonl`. A replay miss is `E_REPLAY_MISS`, never a silent live call.
* Prompts live in `app/prompts/*.md` (hash in `metadata.llm.prompt_hash`). The Validator prompt holds counts and names only.
* Every live run records backend and build, launch flags, GGUF SHA256, quantisation, context size, sampling settings and seed.
* **Not yet verified (Day 1):** that `llama serve` exposes `/v1/chat/completions` with JSON-schema output; if not, the client falls back to "prompt for JSON, validate, retry". Freeze the llama build after Day 1.

---

## 9. Testing contract (detail: `contracts/testing.md`)

### 9.1 What the tests call

The tests call `run(...)` directly (not the API), build each follow-up from its source by **one named transformation**, never reach into agent internals, and assert only on fields of section 6. 
### 9.2 The metamorphic relations (assertions, skip rules, tolerances and targeted faults: `testing.md` §5)

**Required by the assignment (1–8):** MR1 shuffle rows · MR2 price ÷ 100,000 with `price_unit = "lakh"` · MR3a/3b duplicate every row (new / same `listing_id`) · MR4 add X to every price in one month · MR5 widen `price_band` · MR6 restrict `localities` to a subset · MR7 `window_end` + 1 month · MR8 scale prices by k. **Extras:** MR9 paraphrase the sentence · MR10 split by BHK, counts add up · X1 flip topology. Families: invariance (1, 2, 3, 9, X1), monotonic (4, 5, 6, 10), directional (7, 8; MR7 is in substance an invariance on the overlap). Source and follow-up are both checked against the skip rules. **A skip is not a pass**; skips are logged and reported.

### 9.3 Base inputs

One **base input** = one distinct `Criteria` (the unit for counting and confidence intervals; the 3 seeds on one base are not independent). A generator seeded by `GEN_SEED` draws them: 80 % broad (≥ 60 matching rows), 20 % thin (20–59 rows with a price band, which exercises L2). **Mode A** (`LLM_MODE=off`): ≥ 100 bases per MR. **Mode B** (live, then replayed): ≥ 30 bases (50 target) for MR9, plus MR1 and MR3 in AI mode. Details: `testing.md` §4.

### 9.4 Seeds and statistics

Mode A is deterministic: one run per base with `seed = 0` plus the determinism self-test. Mode B runs each base under all `SEEDS` (source and follow-up share the seed, D9); a **base violates** if **any** seed pair violates, and the per-pair rate is also reported. **Violation rate** = violating / evaluated bases, with a 95 % **Wilson** interval, or **Clopper–Pearson** when the count is 0 or n (0 violations: upper bound `1 − 0.025^(1/n)`; n = 30 → 11.6 %, n = 100 → 3.6 %).

### 9.5 Oracle, logs, process

`tests/mt/oracle.py` is an independent plain-pandas implementation of 6.2–6.3 and MUST NOT import application logic; check it against `golden.md` first, then the application against it on every base, and fix any mismatch before MRs run. Pre-register predictions in `NOTEBOOK.md`; diagnose the 3 most-violated MRs with the 5-step protocol; log every violation to `results/violations.csv` and tag `v0-results` before fixing anything. All in `testing.md` §2, §9, §10.

---

## 10. API contract

JSON, CORS on. Domain errors are HTTP 200 with a report whose `status` is `"error"`; HTTP 500 is a crash (a bug). `GET /api/meta` returns `localities`, `bhk_values`, `sale_conds`, `first_month`, `latest_month`, `window_end_min`, `window_end_max`, `default_window_end`, `sales_per_month`, `localities_active_by_month`, `snapshot_sha256`, `constants`, `partial_months`. `POST /api/run` takes `{ "criteria": Criteria }` or `{ "nl_query": str }` plus optional `seed`, `options`, and returns a `TrendReport`. `GET /api/health` returns `{ "status": "ok", "llm_mode", "snapshot_sha256", "logic_version", "contract_version" }`.

**UI rule:** the UI displays application numbers and does no calculations (no medians, percentages or unit conversion); rounding and lakh/crore labels are display only. Build the UI first against a hand-written `example_response.json` (see `golden.md` Appendix B), then switch the API address.

---

## 11. Repository and reproduction contract

```
CONTRACT.md  NOTEBOOK.md  AI_USE.md  README.md  .env.example
contracts/   data.md  llm.md  testing.md  golden.md  agents/ (_common.md, A_…F_*.md, _review.md)
data/raw/Chennai_Housing_Sale.csv   data/chennai_snapshot.csv   data/SNAPSHOT.sha256
scripts/freeze_snapshot.py          scripts/golden_vectors.py
app/   contract.py (constants + pydantic models), orchestrator.py, agents/, llm_client.py, prompts/
api/  ui/
tests/  unit/ (app unit tests), mt/ (oracle.py, generator.py, stats.py, harness.py, mrs/, run.py, reproduce.py),
        mt_selftests/ (tests of mt/)
cache/llm_replay.jsonl     results/ (violations.csv, headline_table.md, run_manifest.json)
docs/ design_note, MR_SPEC.md, report (includes the ½-page reflection)
```

**One-command reproduction:** `python -m tests.mt.reproduce` rebuilds `results/headline_table.md` from the frozen snapshot, `GEN_SEED`, `SEEDS` and `LLM_MODE=replay`, with no GPU and no network. It fails loudly on a snapshot hash mismatch or a replay-cache miss. State in the report that a live run may drift.

---

## 12. Open items and changelog

**Open items:**
1. Both confirm D1–D11, or change them (before Gate 1).
2. Verify that `llama serve` exposes an OpenAI-compatible endpoint with JSON-schema output; record version, flags, GGUF hash; confirm the same GGUF on both machines (Day 1).
3. Check the Kaggle licence wording and add the citation (Day 1).
4. Project name is undecided (not needed by the contract).
5. Write `example_response.json` from section 6 using the golden numbers (Day 1).
6. Redraw the control-flow graph with L1 and L2 marked as cycles, and update the design note (Day 1): `median_price_inr` → `median_price` + `price_unit`; remove L3 (text and graph, including the clean/moderate/severe re-scan branch); give every agent its one-line job and Kind (7.1); use the 6.3 formulas for `coverage_score` and `anomaly_flags`; the Diagnostic runs for every flag; the snapshot has 7,108 rows.
7. Review the **[clarification]** rows in `contracts/agents/_review.md`, `llm.md` §12 and `testing.md` §12 (at T79).
8. Write the ½-page reflection (what an LLM could have produced without running the system, and what it could not) for the report.

| Version | Date | Change | Agreed |
|---|---|---|---|
| 1.0.0 | 2026-10-10 | First full contract, built from the dataset verification. | draft |
| 1.1.0 | 2026-10-10 | (a) D11: the Validator may use the model for the L2 widen/stop choice (I-LLM, 7.1, 7.3, 7.4 `decided_by`, 8). (b) 7.1 gets a Kind column. (c) Fixes promoted from subcontract clarifications: MR3 skip also covers a pooled first-3 / last-3 count in {3, 4}; MR4 means "all fields equal except `pct_change` at m+1". (d) `app/contract.py`; `logic_version`; `FLAT_BAND_PCT` used in 6.2. (e) Size: sections 4, 8, 9 summarised; MR table, cleaning table and appendices moved to subcontracts (`golden.md` is new); `agents.md` sharded into `contracts/agents/`; section 1 added, other numbering unchanged. | draft |
| 1.1.1 | 2026-10-11 | Paths only, no rule change: the test suite moved to `tests/unit/` (app unit tests), `tests/mt/` (MR framework: oracle, generator, stats, harness, MRs, run, reproduce) and `tests/mt_selftests/`. Updated in 9.5, 11, `testing.md` and `data.md` RC7. | ☐ all team members |
| 1.1.2 | 2026-10-15 | Model thinking per use (8, `llm.md` 5). What was wrong: thinking was left to the server default (on), so every Validator and Diagnostic call took about 65–120 s on the canonical machine and a 3-flag run took several minutes; the setting also changed answers without being in the cache key. Now on for the Planner (measured 10/10 vs 9/10 on 10 sentences), off for the Validator and Diagnostic (about 13 s per call), sent in each request, and `thinking` is an eighth cache-key field. Cache entries recorded before this no longer match. | ☐ all team members |
