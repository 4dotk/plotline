# Rules shared by every agent

*Shard of `agents.md` v1.1.0. Every agent reads this file plus its own file. `CONTRACT.md` wins on any conflict. Constants live in `app/contract.py` only.*

**Kinds:** a **worker** (B, C, E, F, H) is a plain function of its inputs. A **decision-maker** (A, D) chooses what happens next, by rule or, where allowed, with the model. G is a **text writer**.

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
| Only A (Planner, AI mode), D (the `widen`/`stop` choice) and G (Diagnostic) may call the model, and only through `app/llm_client.py` (I-LLM, D11). Workers (B, C, E, F, H) never do. Every number in the report comes from code. | global 8, I-LLM |

## Trace and loop bookkeeping

* `trace` events are `{i, agent, kind, loop, msg, data}`; `i` counts from 0 with no gaps; `agent` ∈ `planner|inspector|scanner|aggregator|validator|anomaly|diagnostic|reporter` (`inspector` since 1.2.0); `kind` ∈ `step|decision|loop|warning|error`.
* **Every loop firing is exactly one `kind = "loop"` event** with the exact templates of global 7.4:
  * L1: `L1 fired: {issue}; {before} -> {after}; repair {n} of 2`, `data` keys `issue`, `before`, `after`, `repair_no`, `cap`. Written by agent `planner` at the moment of repair **[clarification]**.
  * L2: see `D_validator.md`.
* "L2 skipped" and "L2 disabled" are **not** loop firings: use `kind = "decision"` (skipped) and `kind = "warning"` (disabled), `loop = null` **[clarification]**, so counting `kind = "loop"` events always equals `loop_counters`.
* Caps are hard: `L1_CAP` = 2 repairs, `L2_CAP` = 3 attempts.
* A model `stop` in L2 is `kind = "decision"`, `loop = null`: not a loop firing.
* L1 is sent by H (Inspector) before the scan; C's identical check before aggregating is a backstop (1.2.0).
* Loop order: L1 can only fire before the first successful aggregation, because widening never produces an invalid criterion. So L2 never triggers L1.
* The snapshot hash check (`E_SNAPSHOT_HASH`) runs at start-up, before agent A; see `contracts/data.md`.

## L1 repair table (H detects, C as backstop; A repairs)

| Issue code | Detected when | Repair |
|---|---|---|
| `band_inverted` | `price_band` has `lo > hi` | swap |
| `locality_unknown` | a locality is not canonical | closest canonical name (`difflib`, cutoff 0.8); no match → cannot repair |
| `window_out_of_range` | `window_end` outside the valid range | clamp to the nearest valid `window_end` |
| `bhk_out_of_range` | a value outside 1–4 | drop the bad value; empty list → cannot repair |
| `sale_cond_unknown` | a sale condition is not canonical | cannot repair |

An inverted `sqft_range` is not an L1 issue: `E_INVALID_CRITERIA` at once.

All repairable issues found in one pass count as **one** repair. Cannot repair, or `L1_CAP` reached → `E_INVALID_CRITERIA` naming the field, and an `out_of_scope` notice (1.2.0).

## Notices (1.2.0)

Only H writes `notices` (global 6.2). Other agents tell the user nothing directly; what H needs comes from the trace (L1 and L2 `loop` events, the Planner's `parse audit` warning) and the data.
