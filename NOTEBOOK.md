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
