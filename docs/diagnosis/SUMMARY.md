# Diagnosis summary (T56 to T58)

**No agent fault confirmed for MR3, MR10 or MR6; no fix applied.** `git diff src/` is empty on this branch.

The top 3 MRs were chosen by unconditioned rate, because every MR has 0 conditioned violations (`results/headline_table.md`).

| MR | Unconditioned (v0) | Class | Mechanism | Page |
|---|---|---|---|---|
| MR3a / MR3b | 142/350 = 40.6 % | Ill-conceived MR at the `MIN_BUCKET_N` margin; data artifact (thin months) | Duplication moves months from n ∈ {3, 4} to 6–8, across the gate, so `pct_change`, flags and the summary appear. On thin bases L2 also takes a different path, so the counts differ. | [MR3.md](MR3.md) |
| MR10 | 108/350 = 30.9 % | Ill-conceived MR under L2 | Each per-BHK run is thinner, so it widens or drops the price band further than the source | [MR10.md](MR10.md) |
| MR6 | 37/226 = 16.4 % | Ill-conceived MR under L2 | The subset is thinner, widens further and ends with more rows than the full set | [MR6.md](MR6.md) |

How each was checked:
* loops on vs off over all 350 v0 bases (`python -m tests.mt.diagnose --mr <MR>`);
* minimal-case traces with an oracle check on every run (`--base-id N`);
* a plain-pandas hand check;
* for MR3, a check of every remaining diff against the gate (`--explain-gate`, 0 unexplained). Run with the loops on, the same check reports 5,221 unexplained diffs, so it can fail.

In every case the existing skip rule is exactly what keeps these diffs out of the conditioned table, so the skip rules stand unchanged.

## MR9 in Mode B (2026-10-17)

The only conditioned violations in the campaign: **2/30 bases** on the live model (OpenRouter, 30 bases × seeds 0, 101, 202). **Class: Planner fault on an ambiguous input; not fixed (code frozen).** Both are seed 101 on "… move in the year to 2010-11?". The model read it as the Indian financial year 2010-11 (`window_end` 2011-03) or as no month at all (null, so the latest month). See [MR9.md](MR9.md).

## Before / after (T60)

**Pre-check on the canonical machine (2026-10-16, branch `diag/day5` at `aeae8d0`):**
* Command: `python -m tests.mt.run --bases 350 --out results/scratch_final`, 7 min 55 s.
* Result: 0 invariant violations and 0 oracle mismatches.
* `headline_table.md`, `violations.csv`, `skips.csv`, `violations_unconditioned.csv` and `bases_and_params.json` are **byte-identical** to the committed `results/` (commit `ab21456`).
* `run_manifest.json` differs only in `contract_version` (1.1.1 → 1.1.2) and `git_commit`.

Against the `v0-results` tag, every count is identical; only the skip-reason labels changed. Since `6f99102`, a base lists every reason that applies, joined with `+`, instead of the first one. For example, MR3 "gate: 144" became "gate: 66; gate + L2: 78". `src/` has changed since `v0-results`:
* F1 `Decimal` fix in `nl_rules.py`;
* the per-agent thinking switch;
* Diagnostic G;
* a refactor of `orchestrator.py` and `state.py`.

None of these reaches a Mode A number, which is consistent with no agent fault having been fixed.

| MR | Conditioned, v0 → now | Unconditioned, v0 → now |
|---|---|---|
| MR1, MR2, MR8 | 0/350 → 0/350 | – |
| MR3a, MR3b | 0/202 → 0/202 | 142/350 → 142/350 |
| MR4 | 0/173 → 0/173 | – |
| MR5 | 0/114 → 0/114 | 13/196 → 13/196 |
| MR6 | 0/169 → 0/169 | 37/226 → 37/226 |
| MR7 | 0/266 → 0/266 | 8/348 → 8/348 |
| MR9 | 0 evaluated (LLM off) | – |
| MR10 | 0/154 → 0/154 | 108/350 → 108/350 |

`TODO(final-results)`: after the real final run (`uv run python -m tests.mt.run --bases 350`, which rewrites `results/`) and the `final-results` tag, confirm that this table still holds.
