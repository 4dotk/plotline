# TESTING SUBCONTRACT — Chennai Housing-Trends Application

**Task:** T76 · **Parent:** `CONTRACT.md` v1.2.0 (the global contract)
**Scope:** oracle rules, metamorphic relations (MRs) with input subdomains and tolerances, test inputs, seeds, statistics, and result logging.

This is a **subcontract**, not a separate global or shared contract. It is derived from `CONTRACT.md` sections 6, 7.2 and 9 and MUST NOT contradict or redefine them. If this file and `CONTRACT.md` disagree, `CONTRACT.md` wins and this file is the defect. Constants (tolerances, seeds, thresholds) are never given new values here; they come from `app/contract.py` (global section 3). Numbers quoted below are for reading only.

Where this file adds a detail the global contract leaves open, the line is marked **[clarification]** and listed in section 12 for the T79 contract check.

---

## 1. What the tests may touch

* The test suite calls `run(...)` directly (not through the API) and builds each follow-up input from its source input by **one named transformation**.
* It asserts only on fields of the `TrendReport` (global 6.2). It never reaches into agent internals.
* It never modifies the dataframe or `Criteria` of a source run; every transformed dataset is a **new** dataframe (I-PURE).
* It reads only the frozen snapshot (`data/chennai_snapshot.csv`, checked against `data/SNAPSHOT.sha256`).
* `notices` (1.2.0) is deterministic: compared where the MR compares the whole report (MR1); IGNORED by MR11 except that a `repaired` notice must be present; not compared elsewhere.
* Fields it does not compare: `diagnostics` and `trace` are IGNORED; `metadata` is IGNORED except where stated (`loop_counters` drives skip rules and diagnosis; `topology` and `n_scanners` were to be compared only in X1, which was cut; MR1 ignores `metadata`).
* `status` and `error.code` are compared EXACT; `error.message` is ignored.

## 2. Oracle rules

`tests/mt/oracle.py` is an independent plain-pandas implementation of every formula in global 6.2–6.3.

1. **Independence.** It MUST NOT import any application logic (`app/`). It may share only the snapshot file and the constants module `app/contract.py`, so thresholds cannot drift. **[clarification]** (constants import is the only allowed `app` import; see section 12)
2. **What it computes:** the dense grid keys (I-DENSE); `listing_count`, `n_in_bucket`, `median_price`, `median_price_per_sqft`, `low_sample`; `pct_change_price_per_sqft`; `anomaly_flags` (`price_jump`, `count_drop`); the summary (pooled first-3 vs last-3 months, `change_pct`, `direction`); `coverage_score`. Medians use numpy `median` semantics on the same rows; no rounding.
3. **Order of use:**
   1. Check the oracle against the golden vectors (`golden.md` A1 for 2015-02, A2 for 2011-12) and against three hand calculations (T23).
   2. Check the application against the oracle on **every** base input.
   3. Any mismatch is a bug in the application, the oracle, or the contract. **Fix it before any MR run.**
4. **Which criteria the oracle is run on.** The oracle computes from the report's `effective_criteria`, so L1 repairs and L2 widening are covered without the oracle re-implementing the loops. **[clarification]** The loops themselves are tested by the L2 worked example (`golden.md` A3: 38 → 49 → 71 rows, 3 → 6 → 9 covered months, `L2_attempts` = 2) and by section 11.
5. **Free invariant checks on every base** (global 7.2): I-DET (run the same input twice → identical bytes), I-PURE (dataframe and `Criteria` hashed before and after the run), I-DENSE (the application's record key set equals the oracle's key set from `effective_criteria`).

## 3. Comparators and tolerances

| Comparator | Definition | Used for |
|---|---|---|
| EXACT | `==` | `status`, `error.code`, counts, `low_sample`, `direction`, `region_key`, `month`, `effective_criteria`, `coverage_score` (integer ratio), flag identity |
| REL_TOL | `|a−b| ≤ REL_TOL × max(|a|,|b|)`; null equals null only | `median_price`, `median_price_per_sqft`, `summary.start/end`, flag `value` |
| ABS_TOL | `|a−b| ≤ ABS_TOL` | `pct_change_price_per_sqft` (a fraction) |
| ABS_TOL_PCT | `|a−b| ≤ ABS_TOL_PCT` | `summary.*.change_pct` (stored in percent) |
| Bit-exact | identical float bits | MR1 only (I-ORDER) |

* Anomaly flags are compared **as a set** on (`month`, `region_key`, `kind`); their `value` by REL_TOL.
* MR3 medians should also come out bit-exact. If they differ by more than 1 ulp, inspect before concluding anything.
* For the MR9 pairs, EXACT means `==` on every compared field including floats (same data, same criteria, deterministic code).

## 4. Base inputs

* **One base input = one distinct `Criteria`** (canonical JSON: keys sorted, lists sorted, numbers as written). Distinct bases are the unit for counting, confidence intervals and independence. The 3 seeds on one base are not independent; say so in threats to validity.
* **Generator** (`tests/mt/generator.py`, seeded by `GEN_SEED`). For each draw:
  1. `window_end` sampled uniformly over the 123 valid ends (never the default);
  2. `localities`: a random subset of those with ≥ 30 sales in that window;
  3. `bhk`: null half the time, else 1–2 values each with ≥ 10 sales;
  4. `price_band`: null half the time, else window price quantiles `q_lo` ∈ [0, 0.4] and `q_hi` ∈ [0.6, 1].
  5. The generator sets no `sqft_range` and no `sale_cond`.
* **Eligibility**, decided on the **unmodified snapshot** before any transformation:
  * *broad stratum*: ≥ 60 matching rows;
  * *thin stratum*: 20–59 matching rows **and** a price band set (these exercise L2).
  * Target mix 80 % broad, 20 % thin (prototype: 78 % of draws were broad, 16 % had 20–59 rows).
* **Counts:** Mode A ≥ 100 bases per MR (all 10 MRs, `LLM_MODE=off`). Mode B ≥ 30 bases (50 target) for MR9, plus MR1 and MR3 in AI mode.
* **Per-MR parameters** (X, δ, k, subset S, month m, paraphrase choices) are drawn from the same seeded stream, so the base list and every parameter regenerate from `GEN_SEED`. They are stored in the result files (section 9).
* The first 100 bases are saved to a file with the seed recorded (T25).
* Every base has a stable `base_id` (its position in generator order, with its canonical JSON stored). **[clarification]**

## 5. Metamorphic relations

MRs 1–8 are the assignment's required eight. MR9, MR10, MR11 (1.2.0) and X1 are extras (task-list "cut order"); if one is cut, update the global contract first (global change rule). **X1 was cut in 1.2.0** (global 9.2): its rows below are kept for the record and were never run.

### 5.1 Transformations

| MR | Family | Transformation (source → follow-up) | Parameters drawn |
|---|---|---|---|
| 1 | Invariance | Shuffle rows (seeded permutation) | permutation seed |
| 2 | Invariance | `price` and `price_band` ÷ 100,000; `price_unit = "lakh"` | none |
| 3a | Invariance | Every row duplicated with **new** `listing_id`s (`<id>_dup`) | none |
| 3b | Invariance | Every row duplicated with the **same** `listing_id`s | none |
| 4 | Monotonic | +X added to `price` of every row in one window month m | X ∈ {250,000; 1,000,000}; m in the window |
| 5 | Monotonic | `price_band` widened by δ of its width on each side | δ ∈ {0.1, 0.3} |
| 6 | Monotonic | `localities` L → a proper non-empty subset S ⊂ L (L null = all 7) | S |
| 7 | Directional | `window_end` + 1 month | none |
| 8 | Directional | `price` and `price_band` × k (`price_unit` unchanged) | k ∈ {2, 4, 10} |
| 9 | Invariance | Paraphrase of the sentence (≥ 4 phrasings per base, including "last year" where it applies) | phrasings |
| 10 | Monotonic (additive) | `bhk` null (or set B) → one run per value b ∈ B | none |
| 11 | Invariance (1.2.0) | Plant every repairable defect the base allows, at once: each locality lower-cased with spaces ("  adyar "), `price_band` high to low, BHK 7 added | none |
| X1 | Invariance (stretch) | `force_topology` flipped | none |

MR7 is labelled Directional because the assignment table does; in substance it is an invariance on the overlap. The MR spec must say so.

### 5.2 Assertions

| MR | Assert | Do **not** assert |
|---|---|---|
| 1 | Whole report except `trace`, `diagnostics`, `metadata`: **bit-exact** floats | — |
| 2 | Counts, flags, `coverage_score`, `direction`: EXACT. `median_price`, `median_price_per_sqft`, `summary.start/end` equal source ÷ 100,000 (REL_TOL). `pct_change`, `change_pct` equal (ABS_TOL / ABS_TOL_PCT) | `price_unit` string |
| 3a, 3b | Counts (`listing_count`, `n_in_bucket`, `summary.n_rows`) ×2 EXACT. Medians, `pct_change`, `summary.start/end/change_pct`, flags equal. 3b violation means the application dedups, which breaks D3 and I-NODEDUPE | `low_sample` |
| 4 | Month m: `median_price` = source + X (REL_TOL), counts EXACT, for every region. Every month ≠ m: all record fields equal, **except `pct_change` at month m+1**. No month's `median_price` decreases | Month m `median_price_per_sqft`; `pct_change` and flags for months m and m+1; `summary` |
| 5 | `listing_count` in follow-up ≥ source for every (month, region) | medians |
| 6 | `ALL.listing_count(S) ≤ ALL.listing_count(L)` per month. Locality records for l ∈ S equal in both runs (EXACT / REL_TOL) | `coverage_score` |
| 7 | The 11 overlapping months: all record fields equal for every region. `pct_change` and flags compared only for the 10 overlap months after the first overlap month | `coverage_score`, `summary`, `n_rows` |
| 8 | Counts, flags, `coverage_score`, `direction`: EXACT. Medians and `summary.start/end` equal source × k (REL_TOL). `pct_change`, `change_pct` equal (ABS_TOL / ABS_TOL_PCT) | — |
| 9 | **First** `effective_criteria` EXACT (set semantics). Then `records`, `summary`, `anomaly_flags`, `coverage_score` EXACT | `diagnostics`, `trace` |
| 10 | Σ over b of `listing_count` = source `listing_count`, per (month, region), EXACT | medians |
| 11 | Whole report **bit-exact** except `trace`, `diagnostics`, `metadata`, `criteria_in`, `notices`; follow-up `L1_repairs` = 1 (EXACT; every defect repaired in one pass); a `repaired` notice is present | `notices` text |
| X1 | Whole report except `metadata.topology` and `metadata.n_scanners` | — |

Notes on application of the table:
* MR4: `pct_change` at month m+1 depends on month m, so it is excluded together with the flags of months m and m+1 (global v1.1.0).
* MR7: with source window months m1…m12 and follow-up m2…m13, `pct_change` and flags are compared for m3…m12.
* MR9: the source phrasing is the canonical sentence; each other phrasing is a follow-up and forms its own pair. A base violates if any pair violates.
* If the **source** report has `status ≠ "ok"` on a generated base, stop: that is a generator, oracle or contract bug, not an MR result. If the **follow-up** has `status ≠ "ok"` while the source is ok, log a violation on field `status`. **[clarification]**

### 5.3 Input subdomain ("skip when") and targeted fault

Skip rules are written only in terms of report fields so they can be checked automatically. **Both** the source and the follow-up are checked.

| MR | Skip when | Targeted fault |
|---|---|---|
| 1 | never | Order-dependent aggregation; non-deterministic worker merges |
| 2 | flag margin: any \|\|pct\| − `ANOMALY_PCT`\| < 1e-9 | Hard-coded unit assumptions; absolute thresholds in anomaly detection |
| 3a | any `ALL` month with `n_in_bucket` ∈ {3, 4}; the pooled first-3-months or last-3-months valid-row count ∈ {3, 4} (the summary gate); `L2_attempts` > 0 | Silent dedup errors; count-weighted median corruption; the `MIN_BUCKET_N` gate |
| 3b | same as 3a | Dedup by `listing_id` (breaks D3) |
| 4 | `price_band` is set; `ALL` `n_in_bucket(m)` < `MIN_BUCKET_N` | Cross-bucket record leakage in monthly aggregation |
| 5 | `price_band` null; `L2_attempts` > 0 in either run | Filter boundary defects; loop pruning dropping rows |
| 6 | \|L\| < 2; `L2_attempts` > 0 in either run | Topology double-counting between parallel and merged workers |
| 7 | `L2_attempts` > 0 in either run; `window_end + 1` beyond the snapshot | Temporal boundary conditions; off-by-one window maths; window-wide state (coverage, L2) |
| 8 | flag margin as in MR2 | Absolute anomaly thresholds firing under scale |
| 9 | never in Mode A since 1.2.0 (the model is stubbed to fail, so the rule parser reads every phrasing); before 1.2.0: `LLM_MODE = off` | Planner (LLM, or the rule parser in Mode A) not mapping paraphrases to the same criteria |
| 10 | `L2_attempts` > 0 in any run; any soft filter set (`price_band`, `sqft_range`, `sale_cond`) | Filter or partition defects; rows lost or double-counted across BHK |
| 11 | precondition: no `localities`, no `price_band` and no `bhk` (nothing to plant) | Wrong L1 repairs (band not swapped, locality matched to the wrong place, valid BHK dropped); repairs taking more than one pass; repairs not told to the user |
| X1 | never | Topology leaking into numbers (I-TOPO) |

## 6. Skips and conditioned / unconditioned reporting

* A **skip is not a pass.** Every skipped base is logged with its MR and reason, and the headline table reports the number of skipped bases per MR and per reason.
* **Conditioned result** (headline): skip rules applied.
* **Unconditioned result**, reported in a second column for MRs 3, 5, 6, 7 and 10: the same MR run on all bases without the report-field skips (`L2_attempts`, `n_in_bucket` margins). A skip that makes the transformation itself undefined (`price_band` null for MR5, \|L\| < 2 for MR6) is never waived. **[clarification]**
* A large gap between the two columns is itself evidence: it points to L2 or the coverage gate, not to the MR being wrong.

## 7. Modes and seeds

| | Mode A | Mode B |
|---|---|---|
| `LLM_MODE` | `off` | `live` on the canonical machine, then `replay` |
| MRs | MR1–MR11 (X1 cut); MR9 through the rule parser, the model stubbed to fail (1.2.0) | MR9; MR1 and MR3 in AI mode (sentence queries), with the Validator's widen/stop decision live |
| Bases | ≥ 100 per MR | ≥ 30 (50 target) per MR |
| Seeds | run each base once with `seed = 0` | all `SEEDS` = (0, 101, 202) (1.2.0) |

* **Mode A:** the application is deterministic by construction. Run the determinism self-test (same input twice → identical bytes, I-DET) on **every** base. State in the report that k = 3 seeds add nothing here, and that with `LLM_MODE=off` the seed changes nothing (the test checks it).
* **Mode B:** a source run and its follow-up use the **same** seed value (D9). A **base violates** if **any** seed pair violates (any-seed rule). Also report the per-pair violation rate as a second number.
* Mode B bases for MR9 must be expressible as a sentence (localities, `window_end`, `bhk`, `price_band`; the generator sets nothing else). The phrasings come from committed templates, not from the LLM, so the base list regenerates from `GEN_SEED`. **[clarification]**
* The "last year" phrasing means `window_end` = 2015-02, so it applies only to bases with that `window_end`. Uniform sampling over 123 ends will rarely produce it, so Mode B reserves a share of its bases for `window_end` = 2015-02. **[clarification]**
* **Status at 2026-10-25:** Mode B was run for MR9, MR1 and MR3 in AI mode, against hosted models (OpenRouter), not the canonical machine. MR9 first ran on 10 bases with seed 0 (`results/mode_b/pilot_tests/seed0/`), then on 30 bases × seeds 0, 101, 202 on `nvidia/nemotron-3-super-120b-a12b:free` (`results/mode_b/nemotron/`, 2/30 bases violate, `docs/diagnosis/MR9.md`). MR9, MR3 and MR1 then ran on 30 bases × seeds 0, 101, 202 on `google/gemma-4-26b-a4b-it:free` (`results/mode_b/gemma26b/`; MR9 4/30 bases violate, MR3a/b 0/20 with 10 skipped, MR1 0/30). Both caches, `cache/llm_replay_nemotron.jsonl` and `cache/llm_replay_gemma26b.jsonl`, are committed. The canonical machine and the model's widen/stop decision are still not covered (global open item 9). On the 10-base run: the harness's I-DET check logged 8 of the 10 bases: two live runs of the same input differed. I-DET is defined only for `off` and `replay` (global 7.2), so this is expected of a live model, not a violation.
* After Mode B is recorded live, the cache `cache/llm_replay.jsonl` is committed (only the canonical machine writes it). Reproduction runs in `replay` mode; a cache miss is `E_REPLAY_MISS` and fails the run loudly.

## 8. Statistics

* **Violation rate** = violating bases / evaluated bases (non-skipped).
* **95 % interval:** Wilson score interval (z = 1.96). When the violation count is 0 or equals n, use Clopper–Pearson.
* For 0 violations in n bases the two-sided upper bound is `1 − 0.025^(1/n)`: n = 30 → 11.6 %, n = 100 → 3.6 %.
* Report per MR: seed list, base count, number evaluated, number skipped (by reason), violation count and rate, CI and the method used, and (Mode B) the per-pair rate.
* `tests/mt/stats.py` is tested on known cases (T24): Wilson on a non-boundary count, Clopper–Pearson at 0 and at n, and the two upper bounds above.
* Threats to validity to state in the report: seeds on one base are not independent; Mode A seeds add nothing; the conditioned table excludes skipped bases; the generator draws only price bands (no `sqft_range` or `sale_cond`), so those soft filters are untested; MR1–MR11 cover only the contract's MRs.

## 9. Result logging

* Every violation is a row in `results/violations.csv` with exactly: `MR`, `base_id`, `seed`, `field`, `source_value`, `follow_up_value`. A violation must **name its field**.
* `results/headline_table.md`: one row per MR with the columns of section 8, plus the unconditioned column for MRs 3, 5, 6, 7, 10.
* `results/run_manifest.json`: snapshot hash, contract version, git commit, seeds, base counts, library versions, LLM metadata (global section 8).
* The base list with each MR's drawn parameters, and every skip (MR, `base_id`, reason), are stored in a results file generated from `GEN_SEED` (for example `results/bases_and_params.json`). **[clarification]** (not in the global repository layout)
* **Before/after rates** are kept for every MR across the `v0-results` and `final-results` tags.

## 10. Process

1. **Pre-register predictions** in `NOTEBOOK.md` before the first full run. Most likely top violations: MR3 (ID dedup or the `MIN_BUCKET_N` gate), MR7 (window-wide state: coverage, first-month predecessor, L2), MR8 and MR2 (an absolute threshold). If reality differs, record it.
2. Run the oracle checks (section 2) and fix any mismatch **before** the MR runs.
3. Log every violation to `results/violations.csv` and **tag `v0-results` before fixing anything.** After the tag, any global-contract change needs a changelog line explaining what was wrong.
4. **Diagnosis protocol** for the 3 most-violated MRs:
   1. shrink to a minimal case;
   2. diff the traces and `loop_counters` between source and follow-up;
   3. rerun with `loops_enabled = false`;
   4. check by hand against the oracle;
   5. classify as **agent fault**, **data artifact**, **ill-conceived MR**, or **tests bug**, with the evidence.
5. The final headline run is tagged `final-results`.
6. **One-command reproduction:** `python -m tests.mt.run --bases 350` rebuilds `results/headline_table.md` from the frozen snapshot and `GEN_SEED` with the model off. It needs no GPU and no network, and fails loudly on a snapshot hash mismatch. Model results are reproduced with `LLM_MODE=replay` from the recorded cache (a miss is `E_REPLAY_MISS`). The report states that a live (non-replay) run may drift.

## 11. Harness self-tests (what must exist)

| Part | Minimum test |
|---|---|
| Harness core (T22) | A dummy MR runs end to end: base → transform → both runs → compare with tolerance → record pass/fail; seed registry records every seed used |
| Oracle (T23) | Matches golden vectors A1 and A2 and three hand calculations |
| Statistics (T24) | Section 8 known cases |
| Generator (T25) | Same `GEN_SEED` gives the same bases and parameters; eligibility strata respected; first 100 bases saved with seed |
| Loop probe | The L2 worked example (A3) reproduces rows 38 → 49 → 71 and `L2_attempts` = 2; a thin-stratum base fires L2 and the trace shows it |
| Skip logic | Each skip rule fires on a hand-built report; a skip is logged, not counted as a pass |
| Transformations | Each transformation returns a new dataframe and leaves the source unchanged (I-PURE) |

## 12. Clarifications this file adds (review at T79)

| # | Point | What this file says | Why it needs a look |
|---|---|---|---|
| 1 | Oracle may import `app/contract.py` | Only the constants, nothing else from `app/` | Global 9.5 says the oracle "must not import application logic code"; constants are not logic, but this should be confirmed |
| 2 | Oracle and L1 / L2 | Oracle runs on `effective_criteria` from the report | The oracle then cannot catch a wrong repair or widening; the L2 example and loop probe cover it |
| 3 | What "≥ 100 bases per MR" counts | Evaluated (non-skipped) bases, so the generator draws enough to reach it | MR4 and MR10 need `price_band` null, MR5 needs it set; skips can cut a pool quickly |
| 4 | MR3 summary gate | **Resolved in global v1.1.0:** the pooled first-3 / last-3 count ∈ {3, 4} is now an MR3 skip rule (section 5.3) | — |
| 5 | "Last year" paraphrase vs uniform `window_end` | Mode B reserves a share of bases with `window_end` = 2015-02 | Global 9.3 samples `window_end` uniformly (1 in 123 is the default month) yet MR9 requires a "last year" phrasing |
| 6 | Unconditioned column | Waives only report-field skips, never skips that make the transformation undefined | Global 9.2 does not say which skips are waived |
| 7 | `status` handling | Source not ok → stop; follow-up not ok → violation on `status` | Global table is silent on error reports inside an MR |
| 8 | MR4 month m+1 | **Resolved in global v1.1.0:** MR4 now reads "all fields equal except `pct_change` at m+1" | — |
| 9 | Results file for bases, parameters, skips | `results/bases_and_params.json` | Not in the global repository layout |
| 10 | Mode B phrasings | Committed templates, not LLM-generated | Keeps the base list reproducible from `GEN_SEED` |

## 13. Traceability to the global contract

| This file | Global contract |
|---|---|
| §1 What the tests may touch | 9.1, 6.2, 5.1 |
| §2 Oracle | 9.5, 6.2, 6.3, 7.2, Appendix A |
| §3 Comparators | 6.2, 3 (`REL_TOL`, `ABS_TOL`, `ABS_TOL_PCT`), 9.2 notes |
| §4 Base inputs | 9.3, 3 (`GEN_SEED`), D1, D2 |
| §5 Metamorphic relations | 9.2, D3, D6 |
| §6 Skips and reporting | 9.2 notes |
| §7 Modes and seeds | 9.4, 3 (`SEEDS`), D9, 8 |
| §8 Statistics | 9.4 |
| §9 Result logging | 9.2 notes, 9.5, 11 |
| §10 Process | 9.5, 11 |

*Version: 1.2.0 (tracks `CONTRACT.md` v1.2.0: MR11, MR9 in Mode A, X1 cut, `notices`, Mode B status).*

*Earlier: 1.1.1 (tracks `CONTRACT.md` v1.1.1). Status: draft, pending agreement at the contract check (T79).*
