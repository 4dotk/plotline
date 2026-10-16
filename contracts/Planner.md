# Agent A — Query Planner

*Shard of `agents.md` v1.1.0. Read **this file and `_common.md` only**. `CONTRACT.md` wins on any conflict.*

**Kind:** decision-maker (rules; the model only in AI mode)

**Constants** (reading only; import from `app/contract.py`, never retype): TOPOLOGY_PARALLEL_MIN_LOCALITIES = 3 · L1_CAP = 2 · DEFAULT_WINDOW_END = "latest" (2015-02)

**Types:** `from app.contract import Criteria, RunOptions, TraceEvent`


**Job:** turn the request into valid `Criteria`; choose the scanner topology; in AI mode ask the LLM to parse the sentence. **LLM:** AI mode only.

| | |
|---|---|
| **Inputs** | `query` (`Criteria` or sentence), the valid month range and canonical locality set taken from `listings_df` (month range = min and max of `sale_date[:7]`), `options`, `seed`, and an L1 repair request from H, or from C as a backstop (issue code, field). |
| **Outputs** | `effective_criteria`, `topology` (`parallel` or `consolidated`), `n_scanners`, trace events. |
| **May change** | `effective_criteria`, topology. Nothing else. |

**Does**
1. **Structured mode:** use the `Criteria` as given. Fill defaults: `localities` = null (all 7), `window_end` = latest month (D2), `price_unit` = `"inr"`. No LLM call.
2. **AI mode:** ask the LLM, through `llm_client`, for a `Criteria` and nothing else. "Last year", "past year", "last 12 months", "this year" all give `window_end` = latest snapshot month. A named month ("12 months ending March 2011") sets that `window_end`. Money words become INR (`1 crore` = 10,000,000; `1 lakh` = 100,000). Unparseable LLM output → fall back to the rule-based parser (the fallback is a `warning` trace event). **(1.2.0)** The prompt asks the model to write every stated value as stated (a year after the data, 5 BHK, a band high to low, a place outside the 7 localities), never to drop or correct it: H checks it and the user is told. **Parse audit:** after the model or the rule parser, any BHK, price, year or size the sentence mentions but the criteria lack is a `warning` trace event starting `parse audit` with `data.fields`; the criteria are not changed (H turns it into a `not_read` notice).
3. **Topology:** `parallel` when `localities` is null or has ≥ `TOPOLOGY_PARALLEL_MIN_LOCALITIES` names (then `n_scanners` = number of localities, 7 if null); otherwise `consolidated` with `n_scanners` = 1. `options.force_topology` overrides the choice.
4. **L1 repair** (when H, or C as a backstop, sends an issue back): apply the L1 repair table in `_common.md`. All repairable issues found in one pass count as **one** repair. Re-choose the topology from the repaired criteria. The pipeline restarts at H.
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

## Tests for this agent

Defaults filled; "last year" → 2015-02 (and the other three phrasings); money words → INR; topology = parallel for null / ≥ 3 localities, consolidated otherwise; `force_topology` override; `E_LLM_OFF`, `E_NL_UNPARSEABLE`, `E_REPLAY_MISS`; `criteria_in` never edited; parse audit warns on a dropped BHK, price, year or size and leaves the criteria unchanged
