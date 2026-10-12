# Agent D — Coverage Validator

*Shard of `agents.md` v1.1.0. Read **this file and `_common.md` only**. `CONTRACT.md` wins on any conflict.*

**Kind:** decision-maker (rule, or the model for `widen`/`stop`)

**Constants** (reading only; import from `app/contract.py`, never retype): MIN_BUCKET_N = 5 · COVERAGE_MIN_MONTHS = 9 · L2_CAP = 3 · L2_WIDEN = (0.20, 0.50, "drop")

**Types:** `from app.contract import Criteria, TrendRecord, TraceEvent`


**Job:** compute `coverage_score`; decide retry or stop. **LLM:** yes, for the `widen`/`stop` choice only; the rule is `widen` when `LLM_MODE=off`.

| | |
|---|---|
| **Inputs** | `records` (the `ALL` series), `effective_criteria`, the **original** `criteria` (as validated), `options.loops_enabled`, the L2 attempt count, `llm_mode`, `seed`. |
| **Outputs** | `coverage_score`, and either "continue" or an L2 request to B with the next widened soft filters. |
| **May change** | Triggers L2. |

**Does**
* `coverage_months` = number of the 12 months whose `ALL` record has `n_in_bucket ≥ MIN_BUCKET_N`. `coverage_score = coverage_months / 12`. Uses the **`ALL` series only** (D4).
* The decision is on the **integer**: pass when `coverage_months ≥ COVERAGE_MIN_MONTHS`. Never compare the float.
* **L2 can fire** when `coverage_months < COVERAGE_MIN_MONTHS`, `loops_enabled` is true, soft filters exist, and attempts < `L2_CAP`. Only then does D **decide**:
  * `LLM_MODE=off` → the rule: `widen`. No model call.
  * `LLM_MODE` ∈ {live, replay} → ask through `llm_client` (purpose `validator`) for exactly `{"action": "widen" | "stop"}`. Malformed output → one `warning` per failure, up to 2 retries, then the rule (`widen`); each fallback is logged.
  * **What the model sees:** counts and names only: `coverage_months`, `need_months`, `attempt`, `cap`, the names of the soft filters that are set, the next `factor`. **Never** a price, sqft, rupee or locality value (keeps MR1, MR2 and MR8 prompts identical).
  * **What the model cannot do:** widen hard filters, choose a factor, pass the cap, or change any number. No call at all when coverage passes, no soft filters exist, loops are off, or the cap is reached.
  * `widen` → do the widening below. `stop` → continue with the low `coverage_score`; write a `kind = "decision"` trace event `L2 stopped by model: coverage {months}/12, need {need}/12` (agent `validator`). This is **not** a loop firing and not an attempt.
* **Widening** (D7: soft filters only: `price_band`, `sqft_range`, `sale_cond`; `localities`, `bhk` and `window_end` are never widened):
  * attempt 1: each range widened by `L2_WIDEN[0]` of its **original** width on each side; attempt 2: by `L2_WIDEN[1]`; attempt 3: all soft filters removed.
  * A range `[lo, hi]` widened by f becomes `[lo − f·(hi−lo), hi + f·(hi−lo)]`, lower end floored at 0.
  * Always measured from the **original** value, never cumulative.
  * `effective_criteria` always shows the widened values.
* Stop as soon as the test passes or `L2_CAP` is reached. At the cap, continue and report the low `coverage_score`.
* Worked check (global 7.4, `golden.md` A3): Adyar, 1 BHK, ₹70–90 lakh, `window_end` 2010-12 → rows 38 → 49 → 71, covered months 3 → 6 → 9, `L2_attempts` = 2.

**Trace** (exact templates, global 7.4). Each firing writes exactly one `kind = "loop"` event, `loop = "L2"`, agent `validator` **[clarification]**:

`L2 fired: coverage {months}/12 below {need}/12; {action}; attempt {n} of 3`
with `data` keys `coverage_months`, `need_months`, `action`, `factor`, `attempt`, `cap`, `effective_price_band`, `decided_by` (`"rule"` or `"llm"`). `factor` mirrors `L2_WIDEN` (0.2, 0.5, `"drop"`).

**Failure / skip behaviour**

| Situation | Result |
|---|---|
| Coverage low, **no soft filters** | trace message `L2 skipped: nothing to widen`; continue; **not** an attempt, `L2_attempts` unchanged |
| Coverage low, `loops_enabled = false` | trace message `L2 disabled`; continue |
| Cap reached | continue with the low `coverage_score`; no error |
| `LLM_MODE=replay`, decision prompt not in the cache | report `E_REPLAY_MISS` (never a live call) **[clarification, listed in `_review.md`]** |

D never raises an error for low coverage.

**Must not:** change `records`, call the model for anything but the `widen`/`stop` choice, put a price or sqft value in the prompt, or widen a hard filter.

## Tests for this agent

Coverage integer test at exactly 8 / 9 / 10 months; worked L2 example A3 (38 → 49 → 71 rows, 3 → 6 → 9 months, 2 attempts); widening from the original, floor at 0; cap stops at 3; "skipped" and "disabled" paths; `loop_counters` equals loop events; model `widen` / `stop` / malformed paths; `stop` is a `decision` event and not a loop firing; prompt holds no price, sqft or locality value
