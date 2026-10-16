# Notebook

## Log

| Date | What |
|---|---|
| 10-10 | Project set up, dataset snapshot frozen, contracts added, smoke test |
| 10-11 | Contracts updated; orchestrator, FastAPI app, test logs |
| 10-11 | Agents: planner, scanner, aggregator, validator, anomaly; LLM client |
| 10-11 | Test oracle; stats (Wilson / Clopper-Pearson); seeded base generator |
| 10-11 | MR harness core + MR1 (shuffle): **0/100** violations |
| 10-11 | Tests split into unit / mt / mt_selftests; contract → 1.1.1; planner prompt fix (`price_unit` never null) |
| 10-12 | T31, T32 |
| 10-12 | pi (via OpenRouter) created an adapter in `src/plotline` instead of an implementation; fixed by hand |
| 10-12 | pi's MR2/MR8 discarded: checks read top-level fields that don't exist, so they could never fail |
| 10-13 | MR2–MR10 written, each with a planted-fault selftest; MR9 query set (50 × 5, 11 "last year"); `docs/MR_SPEC.md` |
| 10-16 | T56–T57: top 3 by unconditioned rate (MR3, MR10, MR6) diagnosed with `tests/mt/diagnose.py` (loops on/off, traces, oracle, hand check): no agent fault; `docs/diagnosis/` |
| 10-16 | T58: nothing to fix, `src/` unchanged. T59: 5 runtime mutants (`tests/mt/mutants.py`); M5 (one-sided L2 widening) caught by no MR and not the oracle, only by unit tests |
| 10-16 | T60 pre-check: 350-base Mode A rerun byte-identical to committed `results/`; counts equal to `v0-results` |
| 10-16 | T61–T62: report drafts `docs/report/01_system.md`, `02_testing.md` |
| 10-16 | planned mutant "count only valid rows" was equivalent (snapshot has 0 invalid rows); caught by checking the data before running, replaced |
| 10-16 | mutant script aborted on the first mutant the schema rejected (M1); fixed to record the failure as a result |
| 10-16 | report draft described UI features it had not checked; removed, now `TODO(ui)` |
| 10-16 | wrote MR7 had the "second-lowest" unconditioned rate (it is the lowest), and that the MR3 diagnosis "corrected" the earlier L2 finding (it confirms it for counts); both caught on re-reading the sources |

## Predictions (before the first full sweep)

Not blind: development probes (100–150 bases) showed 0 violations.

- **MR1, MR2, MR8, MR3, MR4, MR5, MR6, MR10:** 0 violations.
- **MR7:** most likely to violate, if any MR does.
- **MR9:** all skipped, because the LLM is off.
- **Skips:** heavy for MR3 (gate), MR4 (band set), MR5 (no band, or L2) and MR10 (L2).

## First full Mode A sweep (10-13, nothing fixed)

350 bases, `LLM_MODE=off`, seed 0. Took about 12 min.

| MR | Evaluated | Violations | Diffs inside skips |
|---|---|---|---|
| 1, 2, 8 | 350 | 0 | – |
| 3a, 3b | 202 | 0 | 142 (gate 140, L2 2) |
| 4 | 173 | 0 | 111 (band set) |
| 5 | 114 | 0 | 13 (L2) |
| 6 | 169 | 0 | 37 (L2) |
| 7 | 266 | 0 | 8 (L2) |
| 9 | 0 | – | all skipped |
| 10 | 154 | 0 | 108 (L2) |

- **Overall:** oracle mismatches 0; I-DET and I-PURE failures 0.
- **Vs prediction:** right, there are no conditioned violations. Every diff sits inside an L2 or gate skip.
- **Next:** tag `v0-results`, then diagnose MR3. Its `listing_count` diffs inside the gate skip can't come from doubling alone.

## Findings

- **F1** `nl_rules._money`: converting lakh to INR goes through a float. "140.1948 lakh" becomes 14019479.999999998, so a row priced exactly at the band edge is dropped. Only sentence queries reach this code, so the Mode A sweep can't show it.
- **MR3a/3b** (unconditioned 142/350): ill-conceived MR at the `MIN_BUCKET_N` margin; duplication moves n ∈ {3,4} across the gate, and on thin bases L2 takes a different path. With loops off all 657 remaining diffs are gate-explained. [docs/diagnosis/MR3.md](docs/diagnosis/MR3.md)
- **MR10** (108/350): ill-conceived MR under L2; each per-BHK run widens its band further. Loops off: 0 diffs on all 350 bases. [docs/diagnosis/MR10.md](docs/diagnosis/MR10.md)
- **MR6** (37/226): ill-conceived MR under L2; the subset widens further than the full set. Loops off: 226 evaluated, 0 violations. [docs/diagnosis/MR6.md](docs/diagnosis/MR6.md)
- **Mutants:** L2's widening is invisible to every MR (they skip on `L2_attempts > 0`) and to the oracle (it reads `effective_criteria`); only unit tests catch M5. [results/mutants/detection_table.md](results/mutants/detection_table.md)
