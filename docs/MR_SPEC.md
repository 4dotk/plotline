# Metamorphic relation specification

One entry per MR: the relation, the input subdomain it is evaluated on, the tolerance of every compared field, and the fault it is meant to expose. Source of truth: `contracts/Testing.md` §3 and §5 (v1.1.1). Each MR is implemented in `tests/mt/mrs/mrNN_*.py`, and the module docstring repeats its entry.

## Conventions

- **Entry point:** every run calls `run(query, listings_df, seed, options)` and reads only `TrendReport` fields. Each follow-up dataframe is a new frame built by one named transformation. The source frame and `Criteria` are never changed (I-PURE is checked on every base).
- **Matching:** records are matched by key `month/region_key` and anomaly flags by `month/region_key/kind`, never by list position. `trace` and `diagnostics` are ignored. `metadata` is ignored except for `loop_counters` (skip rules), `llm_mode` (MR9) and `topology`/`n_scanners` (MR1).
- **Tolerances:** the constants come from `app/contract.py`.

| Comparator | Rule | Applies to |
|---|---|---|
| EXACT | `==` | counts (`listing_count`, `n_in_bucket`, `summary.n_rows`), `low_sample`, `direction`, `coverage_score`, flag identity, `effective_criteria` |
| REL_TOL | \|a−b\| ≤ `REL_TOL`·max(\|a\|,\|b\|); null equals only null | `median_price`, `median_price_per_sqft`, `summary.start/end`, flag `value` |
| ABS_TOL | \|a−b\| ≤ `ABS_TOL` | `pct_change_price_per_sqft` (a fraction) |
| ABS_TOL_PCT | \|a−b\| ≤ `ABS_TOL_PCT` | `summary.*.change_pct` (in percent) |
| Bit-exact | identical float bits | MR1 only |

- **Two kinds of skip.** A **precondition** skip means the transformation is undefined for that base; it is never waived. A **skip rule** is a condition on report fields, checked on the source and on every follow-up. Report-field skips are waived in the unconditioned column (MR3, MR5, MR6, MR7, MR10).
- **Source and follow-up status.** If the source is not `ok`, the run stops: that is a generator, oracle or contract bug. If a follow-up is not `ok`, it is a violation on `status`.
- **Parameters:** all drawn per base from the `GEN_SEED` stream and stored in `results/bases_and_params.json`.

## The relations

| MR | Family | Transformation (source → follow-up) | Relation asserted | Input subdomain: precondition / skip when | Tolerances | Fault it would expose |
|---|---|---|---|---|---|---|
| **1** | Invariance | Rows shuffled by a seeded permutation (`MR1.permutation_seed`) | Whole report except `trace`, `diagnostics`, `metadata` identical; `metadata.topology` and `n_scanners` equal | Never skipped | Bit-exact floats; EXACT otherwise | Order-dependent aggregation; non-deterministic merges of parallel workers (I-ORDER) |
| **2** | Invariance | `price` and `price_band` ÷ 100,000; `price_unit = "lakh"` | Counts, `low_sample`, `summary.n_rows`, flags, `coverage_score`, `direction` unchanged. `median_price`, `median_price_per_sqft`, `summary.start/end` = source ÷ 100,000. `pct_change`, `change_pct` unchanged. The `price_unit` string is **not** asserted | Skip: flag margin, any ALL month with \|\|pct\| − `ANOMALY_PCT`\| < 1e-9, in either run | EXACT; REL_TOL on scaled money; ABS_TOL / ABS_TOL_PCT on percentages | Hard-coded unit assumptions (INR rounding, absolute rupee constants); absolute thresholds in anomaly detection |
| **3a** | Invariance | Every row duplicated; the copy gets a **new** `listing_id` `<id>_dup` | `listing_count`, `n_in_bucket`, `summary.n_rows` = 2 × source. Medians, `pct_change`, `summary.start/end/change_pct`, flags unchanged. `low_sample` is **not** asserted | Skip (either run): any ALL month with `n_in_bucket` ∈ {3, 4}; the pooled first-3 or last-3 month valid-row count ∈ {3, 4}; `L2_attempts` > 0 | EXACT counts; REL_TOL medians and start/end; ABS_TOL pct; ABS_TOL_PCT change_pct | Silent dedup; count-weighted median corruption; `MIN_BUCKET_N` gate off-by-one |
| **3b** | Invariance | Every row duplicated with the **same** `listing_id` | As 3a. A violation means the application dedups, which breaks D3 and I-NODEDUPE | As 3a | As 3a | Dedup by `listing_id` |
| **4** | Monotonic | +X on `price` of every row sold in window month m (X ∈ {250,000; 1,000,000}, m in the window) | Month m, every region: `median_price` = source + X, counts unchanged. Every month ≠ m: all record fields unchanged, except `pct_change` at m+1. Flags unchanged outside m and m+1. No month's `median_price` decreases. Not asserted: month-m `median_price_per_sqft`; `pct_change` and flags at m and m+1; `summary` | Skip (either run): `price_band` set in `effective_criteria`; ALL `n_in_bucket(m)` < `MIN_BUCKET_N` | REL_TOL on +X and medians; EXACT counts; ABS_TOL pct | Cross-bucket leakage in monthly aggregation (rows assigned to the wrong month) |
| **5** | Monotonic | `price_band` [lo, hi] → [lo − δw, hi + δw] with w = hi − lo, δ ∈ {0.1, 0.3} | `listing_count`(follow-up) ≥ `listing_count`(source) for every (month, region); same key set. Medians **not** asserted | Precondition: `price_band` null. Skip: `L2_attempts` > 0 in either run | EXACT (an integer comparison) | Filter boundary defects (inclusive/exclusive, unit); loops or pruning dropping rows when the band widens |
| **6** | Monotonic | `localities` L → a proper non-empty subset S ⊂ L (`MR6.subset`; L null = all 7) | Per month, ALL `listing_count`(S) ≤ ALL `listing_count`(L). The records of each l ∈ S are unchanged, and no region outside S appears. `coverage_score` is **not** asserted | Precondition: \|L\| < 2. Skip: `L2_attempts` > 0 in either run | EXACT counts and `low_sample`; REL_TOL medians | Topology double-counting between parallel workers and the consolidated merge |
| **7** | Directional (in substance an **invariance on the overlap**) | `window_end` + 1 month | With source months m1…m12 and follow-up m2…m13: on the 11 overlap months m2…m12, every region, all record fields unchanged. `pct_change` and flags are compared only on m3…m12 (m2 has no predecessor in the follow-up). Not asserted: `coverage_score`, `summary`, `n_rows` | Precondition: `window_end` + 1 beyond the snapshot. Skip: `L2_attempts` > 0 in either run | EXACT counts; REL_TOL medians and flag values; ABS_TOL pct | Off-by-one window maths; temporal boundary handling; window-wide state leaking into monthly values (coverage, L2, outlier trimming) |
| **8** | Directional | `price` and `price_band` × k, k ∈ {2, 4, 10}; `price_unit` unchanged | As MR2 with the factor k: counts, flags, `coverage_score`, `direction` unchanged; medians and `summary.start/end` = source × k; `pct_change`, `change_pct` unchanged | Skip: flag margin as in MR2, in either run | As MR2 | Absolute (non-scale-free) thresholds: anomaly cut-offs or price sanity floors in rupees |
| **9** | Invariance | The canonical sentence → each of ≥ 4 paraphrases from committed templates; bases at the latest month get "last year" / "past 12 months" wordings | **First** `effective_criteria` identical (set semantics). Only then `records`, `summary`, `anomaly_flags`, `coverage_score` identical. Each paraphrase is its own pair; a base violates if any pair does | Skip: `LLM_MODE = off` (`metadata.llm_mode`, any run). In Mode A every base skips: a sentence is `E_LLM_OFF` by design. Mode B query set: `tests/mt/queries/mr9_paraphrases.json` | EXACT, including floats | The Planner (LLM) mapping paraphrases to different criteria: units, month names, "last year", locality order, BHK wording |
| **10** | Monotonic (additive) | `bhk` null (B = `BHK_VALUES`) or set B → one run per b ∈ B with `bhk = [b]` | Σ over b of `listing_count` = source `listing_count`, per (month, region); same key set in every run. Medians **not** asserted | Skip: `L2_attempts` > 0 in any run; any soft filter (`price_band`, `sqft_range`, `sale_cond`) set in any run's `effective_criteria` | EXACT | Filter or partition defects: rows lost or double-counted across BHK values |

## How each MR's power was checked

Each MR has a selftest in `tests/mt_selftests/test_mr*.py`. It plants a fault in the targeted family and asserts that the MR reports it on the named field. The faults are injected as replacement agents or as a wrapper around `run`, never inside `app/`:

| MR | Planted fault | Caught on |
|---|---|---|
| 1 | ALL median = the first row of the bucket | `records.*/ALL.median_price` |
| 2 | Medians rounded to whole rupees | `records.*.median_price` |
| 3b (not 3a) | Scanner drops repeated `listing_id`s | `records.*.listing_count` |
| 4 | Sales from the 28th onward counted in the next month | `records.*.median_price` |
| 5 | A band wider than a fixed rupee width is cut to that width | `records.*.listing_count` |
| 6 | The parallel topology counts one locality twice | `records.*.listing_count` |
| 7 | Rows above a window-wide price quantile dropped | record fields on the overlap |
| 8 | Rows under a fixed rupee price dropped | `records.*.n_in_bucket` |
| 10 | Single-BHK requests also drop "Partial" sales | `records.*.listing_count` |

MR9 has no planted fault in Mode A, because sentence queries need the LLM there. Its selftests check three things instead: the shape of the query set, that every phrasing is read by the rule parser as the base criteria, and that the criteria comparison comes first.

## Threats to validity specific to these MRs

- **Untested filters:** the generator sets only `price_band`, so `sqft_range` and `sale_cond` are never transformed.
- **MR4 and MR10 subdomain:** these only see bases without a band (after skips), and MR5 only bases with one.
- **Skip-heavy MRs:** MR3, MR5, MR6, MR7 and MR10 skip on `L2_attempts` > 0. That excludes thin bases, which is why the unconditioned column is reported for them.
- **MR9:** the paraphrases come from templates. They show how robust the Planner is to these wordings, not to free user text.
