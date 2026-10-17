# Report draft, part 2: testing

*Draft (T62). Every number names its source file. Full per-MR detail is in `docs/MR_SPEC.md`; the diagnosis is in `docs/diagnosis/`.*

## 1. MR catalogue

Comparators: EXACT `==`; REL_TOL relative 1e-9; ABS_TOL absolute 1e-9 (fractions); ABS_TOL_PCT for `change_pct`; bit-exact for MR1 (`src/plotline/contract.py`, `docs/MR_SPEC.md`).

| MR | Relation (source → follow-up ⇒ assertion) | Family | Subdomain (precondition / skip) | Tolerance | Targeted fault |
|---|---|---|---|---|---|
| 1 | Shuffle rows ⇒ report identical | Invariance | All bases | Bit-exact | Order-dependent aggregation, non-deterministic merges (I-ORDER) |
| 2 | Prices ÷ 100,000, unit `lakh` ⇒ counts and flags unchanged; money ÷ 100,000 | Invariance | Skip: a flag within 1e-9 of `ANOMALY_PCT` | EXACT; REL_TOL money | Hard-coded INR assumptions; absolute thresholds |
| 3a | Duplicate every row (new id) ⇒ counts × 2; medians, pct, flags unchanged | Invariance | Skip: ALL `n_in_bucket` ∈ {3, 4}; pooled gate ∈ {3, 4}; L2 fired | EXACT counts; REL_TOL medians | Silent dedup; count-weighted medians; gate off-by-one |
| 3b | Duplicate every row (same id) ⇒ as 3a | Invariance | As 3a | As 3a | Dedup by `listing_id` (breaks D3) |
| 4 | +X on prices in month m ⇒ median(m) + X; other months unchanged | Monotonic | Skip: `price_band` set; ALL `n_in_bucket(m)` < 5 | REL_TOL; EXACT counts | Rows assigned to the wrong month |
| 5 | Widen `price_band` by δ ∈ {0.1, 0.3} ⇒ every count ≥ | Monotonic | Precondition: band set. Skip: L2 fired | EXACT | Filter boundary (inclusive/exclusive, unit) |
| 6 | Localities L → subset S ⇒ ALL count(S) ≤ ALL count(L); S's records unchanged | Monotonic | Precondition: \|L\| ≥ 2. Skip: L2 fired | EXACT counts; REL_TOL medians | Topology double-counting |
| 7 | `window_end` + 1 ⇒ the 11 overlap months unchanged | Directional (invariance on the overlap) | Precondition: room in the snapshot. Skip: L2 fired | EXACT; REL_TOL; ABS_TOL | Off-by-one windows; window-wide state |
| 8 | Prices × k, k ∈ {2, 4, 10} ⇒ counts and flags unchanged; money × k | Directional | Skip: flag margin | As MR2 | Absolute rupee thresholds |
| 9 | Sentence → paraphrase ⇒ same `effective_criteria`, then the same report | Invariance | Needs the LLM (Mode B); every base skips in Mode A | EXACT | Planner maps paraphrases differently |
| 10 | Split by BHK ⇒ Σ per-BHK counts = source count | Monotonic (additive) | Skip: L2 fired; any soft filter set | EXACT | Rows lost or double-counted across BHK |

Each MR except MR9 has a planted-fault selftest that it catches (`tests/mt_selftests/`, table in `docs/MR_SPEC.md`).

## 2. Results (Mode A, `LLM_MODE=off`, 350 bases, seed 0)

`TODO(final numbers)`: replace with `results/headline_table.md` at the `final-results` tag. The table below is the current committed run (commit `ab21456`, identical in counts to `v0-results`; reproduced byte-identically on 2026-10-16, see `docs/diagnosis/SUMMARY.md`).

| MR | Evaluated | Skipped | Violations, rate [95 % CI] | Unconditioned |
|---|---|---|---|---|
| MR1 | 350 | 0 | 0/350 = 0.0 % [0.0, 1.0] CP | – |
| MR2 | 350 | 0 | 0/350 = 0.0 % [0.0, 1.0] CP | – |
| MR3a | 202 | 148 | 0/202 = 0.0 % [0.0, 1.8] CP | 142/350 = 40.6 % [35.6, 45.8] W |
| MR3b | 202 | 148 | 0/202 = 0.0 % [0.0, 1.8] CP | 142/350 = 40.6 % [35.6, 45.8] W |
| MR4 | 173 | 177 | 0/173 = 0.0 % [0.0, 2.1] CP | – |
| MR5 | 114 | 236 | 0/114 = 0.0 % [0.0, 3.2] CP | 13/196 = 6.6 % [3.9, 11.0] W |
| MR6 | 169 | 181 | 0/169 = 0.0 % [0.0, 2.2] CP | 37/226 = 16.4 % [12.1, 21.8] W |
| MR7 | 266 | 84 | 0/266 = 0.0 % [0.0, 1.4] CP | 8/348 = 2.3 % [1.2, 4.5] W |
| MR8 | 350 | 0 | 0/350 = 0.0 % [0.0, 1.0] CP | – |
| MR9 | 0 | 350 (`LLM_MODE = off`) | n/a | – |
| MR10 | 154 | 196 | 0/154 = 0.0 % [0.0, 2.4] CP | 108/350 = 30.9 % [26.2, 35.9] W |

CP = Clopper–Pearson, W = Wilson. On every base: 0 oracle mismatches and 0 I-DET or I-PURE failures (`results/run_manifest.json`). The skip reasons per MR are in `results/headline_table.md`; every skip is listed in `results/skips.csv`.

**Against the predictions** (`NOTEBOOK.md`, made before the first full run):
* 0 violations for MR1–8 and MR10, and MR9 fully skipped: **correct**.
* MR7 as the most likely MR to violate: **wrong**. It has 0 conditioned violations and the lowest unconditioned rate (2.3 %).
* The heavy skips we predicted for MR3, MR4, MR5 and MR10: **correct**.

## 3. Statistics

Violation rate = violating bases / evaluated (non-skipped) bases (`contracts/Testing.md` §8). The 95 % interval is the Wilson score interval (z = 1.96). When the count is 0 or n, Clopper–Pearson is used; for 0 in n its upper bound is `1 − 0.025^(1/n)`.

Worked example: MR1, 0 violations in n = 350 → upper bound 1 − 0.025^(1/350) = 1 − e^(ln 0.025 / 350) = 1 − e^(−0.010540) = **1.05 %**. The table shows it as 1.0 %. In words: with 95 % confidence, MR1's true violation rate on this base distribution is below about 1 %. For MR5 (n = 114) the same bound is 3.2 %. The skip-heavy MRs give the weakest guarantee.

`tests/mt/stats.py` is tested on the known cases (`tests/mt_selftests/test_stats.py`).

## 4. Diagnosis of the top 3 MRs

There are no conditioned violations, so the three MRs with the highest **unconditioned** rate were diagnosed with the protocol of `contracts/Testing.md` §10.4:
1. shrink to a minimal case;
2. diff the traces;
3. rerun with `loops_enabled = false`;
4. check against the oracle and by hand;
5. classify.

| MR | Unconditioned | Mechanism | Loops off | Class |
|---|---|---|---|---|
| MR3a/3b | 142/350 | Duplication moves months from n ∈ {3, 4} across `MIN_BUCKET_N` = 5, so `pct_change` and flags change. On thin bases L2 also takes a different path. | 140 of 142 still differ; all 657 remaining diffs are explained by the gate, 0 unexplained | Ill-conceived MR at the gate margin / data artifact |
| MR10 | 108/350 | Each per-BHK run is thinner and widens (or drops) the price band further than the source | 0 of 108 differ; all 350 bases have 0 diffs | Ill-conceived MR under L2 |
| MR6 | 37/226 | The subset is thinner and widens further, so its ALL count exceeds the full set's | 0 of 37 differ; 226 evaluated, 0 violations | Ill-conceived MR under L2 |

* **No agent fault** was found. The oracle agrees with the application on all source and follow-up runs of the minimal cases. A plain-pandas hand check reproduces each diff exactly: for MR10 base 321, Σ per BHK = 80 ≠ 73, but with the source's band held fixed Σ = 73.
* The skip rules are therefore justified by evidence, not assumed. The large gap between the conditioned and unconditioned columns comes from L2 and the gate, as `Testing.md` §6 anticipated.
* Details: `docs/diagnosis/MR3.md`, `MR10.md`, `MR6.md`.

## 5. Mutant testing

Five bugs were planted at runtime in the Aggregator and Validator with `unittest.mock.patch`. The source files are never edited (`python -m tests.mt.mutants --bases 60`; full table in `results/mutants/detection_table.md`, failing test ids in `results/mutants/detection.json`). The table uses the first 60 v0 bases, Mode A. Cells give conditioned violations / evaluated bases; MRs that caught nothing are left out.

| Mutant | Change | Reports changed | Caught by MRs | Oracle (bases) | Unit-test failures* | Caught by |
|---|---|---|---|---|---|---|
| baseline | none | 0/60 | all 0 | 0 | 0 | – |
| M1 | `aggregator._record`: `low_sample = n <= MIN_BUCKET_N` | – (the run fails) | – | – | 27 | the `TrendRecord` schema check; unit tests |
| M2 | `aggregator._record`: mean in place of median for ₹/sqft | 60/60 | MR1 60/60 | 60 | 1 | MR1, oracle, unit test |
| M3 | `aggregator._median`: drop the first value in row order | 60/60 | MR1 60/60, MR3a 43/43, MR3b 43/43 | 60 | 1 | MR1, MR3a/b, oracle, unit test |
| M4 | `validator.coverage_months`: `>` in place of `>=` | – (the run fails) | – | – | 20 | the `TrendReport` coverage check; unit tests |
| M5 | `validator._widen_range`: widen only the upper end | 10/60 | **none** | **0** | 2 | **unit tests only** |

\* Failing test results in `tests/unit` under the patch; subtests are counted separately.

* **Two mutants never reach an MR.** The application's own contract validators reject the inconsistent report: `low_sample` must equal `n_in_bucket < MIN_BUCKET_N`, and `coverage_score` must match the ALL series (`src/plotline/contract.py`). That is defence in depth, but it means no MR's sensitivity to these off-by-ones was measured.
* **MR1 catches M2 because of row order, not because of the mean.** `np.mean` sums in row order, so after a shuffle the result differs in its last bits, and MR1 compares bit-exactly. No MR that scales (MR2, MR8) or duplicates (MR3) can see a mean used in place of a median, because a mean scales and duplicates the same way a median does. Only the oracle detects the wrong statistic itself.
* **M5 escapes every MR and the oracle.** The oracle recomputes from the report's own `effective_criteria`, so a wrongly widened band looks correct to it (`contracts/Testing.md` clarification 2). Every MR that would notice (MR5, MR6, MR7, MR10, MR3) skips bases where `L2_attempts > 0`. Only the validator's unit tests (`test_steps_measured_from_the_original`, `test_floor_at_zero_and_sqft_and_sale_cond`) catch it. This is the clearest blind spot of the MR suite: **L2 itself is tested only by unit tests.**

## 6. Free-text evaluation (added 10-16)

The MT campaign runs only structured, valid criteria with the model off (Mode A). The path a user actually takes, a sentence → Planner (model, with the rule parser as fallback) → L1, was covered by 20 hand-written sentences, and the live check passed any *valid* reading. A live query from the UI exposed this: "5bhk flats from 90 to 70 lakhs" came back `ok` for every BHK (F2, `NOTEBOOK.md`).

`tests/nl_eval_queries.py` adds 34 sentences in 7 categories: BHK forms, money forms, inverted ranges, time, places (misspelt, unknown, negated), size and sale condition, and noise or instructions in the text. Each has an expected reading, or an expected error where the contract or a marked POLICY choice says so. A run is classed as **right**, **flagged** (wrong, but the parse audit warned), **silent** (wrong, `ok`, no warning) or **error**. Run with `scripts/smoke_20_queries.py --queries tests.nl_eval_queries [--rules-only]`.

| Parser | Right | Flagged | Silent | Error | Source |
|---|---|---|---|---|---|
| Rules only, before the F2 fixes | 26/34 | 2 | 6 | 0 | `results/nl_eval/rules_before_fixes.jsonl` |
| Rules only, after the F2 fixes | 32/34 | 1 | 1 | 0 | `results/nl_eval/rules_after_fixes.jsonl` |
| Model (gemma-4-e4b, live) | `TODO(number)` | | | | `results/nl_eval/model_live.jsonl` |

Still silent after the fixes: a place outside the data ("homes in Mylapore") is answered for all 7 localities.

## 7. Threats to validity

From `contracts/Testing.md` §8:
* seeds on one base are not independent;
* Mode A seeds add nothing (the application is deterministic, and I-DET is checked on every base);
* the conditioned table excludes skipped bases;
* the generator draws only price bands, so `sqft_range` and `sale_cond` are untested;
* MR1–MR11 cover only the contract's MRs.

Added by this round:
* **The oracle cannot see a wrong L2 widening.** It recomputes from the report's own `effective_criteria` (`Testing.md` clarification 2). Mutant M5 (one-sided widening) changes reports, but no MR and not the oracle catches it (section 5).
* **The skip rules that make the relations sound also hide L2.** Every MR that skips on `L2_attempts > 0` is blind to faults that occur only when L2 fires. A loops-off variant (as used in the diagnosis) would test MR6 on 57 more bases, and MR10 on its 196 soft-filter bases if its soft-filter skip were dropped for that variant (all 350 have 0 diffs with the loops off).
* **Mode B is MR9 only, on a hosted model.** MR9 ran live on 30 bases × 3 seeds (OpenRouter, not the canonical machine; 2/30 bases violate, `docs/diagnosis/MR9.md`). MR1 and MR3 in AI mode and the model's widen/stop decision are untested. The 3 seeds on one base are not independent, and the phrasings come from 5 fixed templates, so the result covers those wordings only.
* **What the MT results cover.** "0 violations" holds for the aggregation pipeline on valid, structured queries with the model off. It says nothing about the sentence path, which is the one users take (section 6).
* **L1 is not reached by MT.** It fired in 0 of 7,059 Mode A runs: the generator draws only valid criteria, and no MR makes them invalid. L1 is exercised by unit tests and by free text (section 6), not by the MR campaign.
* **No adequacy criterion was fixed in advance.** Nothing signalled that the suite never touched L1, the sentence path or the Planner. The suite was declared complete on its own pass rate. Mutants were planted only in the Aggregator and Validator, not in the Planner, where F2 was.
* **Test inputs written by the same people (and tools) as the parser.** All 20 original sentences wrote "2 bhk" with a space, the same assumption the parser made. The live check passed any valid reading, so it could not fail on a wrong one (F2).
* **Model availability.** The model server serves one request at a time on CPU. With a 120 s timeout and 3 attempts, a busy server sends the Planner to the rule fallback without the user being told, other than in the trace.
