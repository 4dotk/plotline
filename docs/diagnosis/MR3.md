# Diagnosis: MR3a / MR3b (duplicate every row)

**Class: ill-conceived MR at the `MIN_BUCKET_N` margin (plus L2 on thin bases). No agent fault.** The skip rule already excludes every affected base. MR3a and MR3b give identical numbers in every step below, so the application does not deduplicate (D3 holds).

## Why MR3 was picked

0 conditioned violations out of 202 evaluated. The unconditioned rate is the highest of any MR: **142/350 = 40.6 %** (`results/headline_table.md`).

## Evidence (T56)

**1. Diff bases by skip reason** (`results/violations_unconditioned.csv`, MR3a; MR3b is identical):

| Skip reason (v0) | Bases with diffs |
|---|---|
| `ALL n_in_bucket in {3,4}` only | 63 |
| `ALL n_in_bucket in {3,4}` + `L2_attempts > 0` | 77 |
| `L2_attempts > 0` only | 2 |
| **Total** | **142** |

In the 63 gate-only bases, the only fields that differ are `pct_change_price_per_sqft` (178 diffs) and `anomaly_flags` (51). There are no count or median diffs.

**2. Loops on vs off** (`uv run python -m tests.mt.diagnose --mr MR3a --mr MR3b` → `results/diagnosis/MR3a_loops.csv`):

| | Bases |
|---|---|
| Diffs with loops on | 142 |
| … still differing with loops off | **140** |
| Diffs only with loops off (35, 327) | 2 |
| Soft filters in `effective_criteria` differ between source and follow-up | 65 of 142 |

Outcomes are identical with loops on and off: 202 pass and 148 skip in both runs. Turning L2 off removes the count and median diffs, but **not** the gate diffs. This confirms the earlier finding (`AI_USE.md`) that MR3's **count** diffs come from L2: 79 bases have L2 firing in the source. It adds that the gate explains the `pct_change` and flag diffs, which remain in 140 bases without L2.

**3. Every diff left with the loops off is explained by the gate** (`uv run python -m tests.mt.diagnose --mr MR3a --explain-gate`):

```
MR3a: 142 bases still differ with loops off
      525  pct_change at a month (or predecessor) with n in {3,4}
      116  anomaly_flags (follow from pct_change / count_drop on the same months)
       16  summary (pooled first-3/last-3 gate)
  unexplained: 0 []
```

The check can fail. The same check run with the loops **on** reports 5,221 unexplained diffs (the L2 count and median changes).

**4. Minimal cases and traces:**

* **Gate only: base 165** (T Nagar, window to 2011-02, no soft filters, 61 rows; `results/diagnosis/MR3a_base165_trace.txt`). In the source, L2 does not fire because there is nothing to widen; the duplicated follow-up reports `coverage 11/12 meets 9/12`. Neither run has an L2 attempt, and the effective criteria are identical.
* **L2 path: base 324** (T Nagar, price band, 21 rows; `MR3a_base324_trace.txt`):
  ```
  SOURCE    L2 fired: coverage 0/12 …; 1/12 …; 5/12 … drop soft filters; attempt 3 of 3  → price_band None
  FOLLOW-UP L2 fired: coverage 4/12 …; 7/12 … widen 50%; attempt 2 of 3; coverage 10/12 → price_band [11232745, 20570365]
  ```
  Duplication doubles every bucket, so coverage is reached earlier and the two runs end with different `effective_criteria`. With the loops off, this base's 80 diffs drop to 6, and the gate explains all 6.

## Oracle and hand check (T57)

* **Oracle** on each run's own `effective_criteria` and frame: 0 mismatches in the source and the follow-up of bases 165 and 324 (trace files, `oracle_mismatches=0`). In the v0 sweep it was also 0 on all 350 source runs (`results/run_manifest.json`).
* **Hand check, base 165**, in plain pandas (`locality == "T Nagar"`, the 12 months to 2011-02, median of `price/sqft`):

  | Month | n | 2n | median ₹/sqft |
  |---|---|---|---|
  | 2010-08 | 6 | 12 | 8234.53 |
  | 2010-09 | **3** | 6 | 11866.78 |
  | 2010-11 | 8 | 16 | 7229.49 |
  | 2010-12 | **3** | 6 | 8520.64 |

  2010-09: source `pct_change` is null (n = 3 < 5); follow-up = 11866.78 / 8234.53 − 1 = **0.44110**. The v0 diff row records 0.44109907. 2010-12: 8520.64 / 7229.49 − 1 = **0.17859**; the diff row records 0.17859465. The two extra `price_jump` flags at 2010-09 and 2010-12 follow from these values. 2010-10 (n = 2 → 4) stays below the gate in both runs and correctly does **not** differ.

## Classification

**Ill-conceived MR at the gate margin; data artifact on thin months.** The application is correct:
* `pct_change` is defined only when both months have `n_in_bucket ≥ MIN_BUCKET_N` (`GLOBAL_CONTRACT.md` §6.3);
* duplicating moves n from 3–4 to 6–8, across the gate;
* L2 depends on coverage, and coverage depends on n.

The invariance "duplicate → medians and pct_change unchanged" holds only away from the gate, and only when L2 takes the same path in both runs. That is exactly what the MR3 skip rule encodes (`docs/MR_SPEC.md`). It is the right rule: no diff exists outside it.
