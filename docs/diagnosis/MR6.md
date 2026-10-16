# Diagnosis: MR6 (locality subset: ALL count of S ≤ ALL count of L)

**Class: ill-conceived MR when L2 fires (the subset widens further than the full set). No agent fault.** With the loops off, the relation holds on all 226 bases where it applies.

## Why MR6 was picked

0 conditioned violations out of 169 evaluated. The unconditioned rate is **37/226 = 16.4 %** (`results/headline_table.md`), the third highest.

## Evidence (T56)

**1. Diff bases by skip reason** (`results/violations_unconditioned.csv`): all 37 are `L2_attempts > 0`. The fields are `listing_count` (449 diffs), `n_in_bucket` (393), medians (372 each) and `low_sample` (168).

**2. Loops on vs off** (`uv run python -m tests.mt.diagnose --mr MR6` → `results/diagnosis/MR6_loops.csv`):

```
MR6: 350 bases; 37 with diffs (loops on); 0 of those still differ with loops off;
     37 of 37 have different soft filters in effective_criteria
```

| Outcome | Loops on | Loops off |
|---|---|---|
| pass | 169 | **226** |
| skip, L2 | 57 | 0 |
| skip, precondition \|L\| < 2 | 124 | 124 |
| violation | 0 | **0** |

With the loops off, the 57 L2-skipped bases are evaluated, and all of them pass.

**3. Minimal case: base 244** (L = Adyar + T Nagar, S = T Nagar, window to 2007-12, price band ₹9.63M–11.83M, 48 rows; `results/diagnosis/MR6_base244_trace.txt`):

```
SOURCE (L)    L2 fired: coverage 5/12 below 9/12; widen 20%; attempt 1 of 3 → coverage 10/12
              price_band [9194042, 12265873]
FOLLOW-UP (S) L2 fired: coverage 0/12 … 20% … 50% … drop soft filters; attempt 3 of 3
              L2 cap reached: coverage 8/12; price_band None
```

The subset is thinner, so it ends with **no** price band, and its ALL count goes above the full set's.

## Oracle and hand check (T57)

* **Oracle**: 0 mismatches in the source and the follow-up of base 244 (`oracle_mismatches=0`).
* **Hand check** in plain pandas (the 12 months to 2007-12). ALL(L) = Adyar + T Nagar within [9194042, 12265873]; ALL(S) = T Nagar with no band. These are the months where S > L:

  | Month | ALL(L) | ALL(S) |
  |---|---|---|
  | 2007-03 | 1 | 4 |
  | 2007-04 | 6 | 8 |
  | 2007-05 | 6 | 10 |
  | 2007-06 | 3 | 6 |
  | 2007-09 | 7 | 10 |
  | 2007-10 | 6 | 11 |

  These are exactly the six `ALL.listing_count` diff rows for base 244 in `results/violations_unconditioned.csv`.

## Classification

**Ill-conceived MR under L2.** "A subset never has more rows" holds only for the same filters. L2 widens per query (D7), and a subset with fewer rows widens more. The `L2_attempts > 0` skip is the right rule. MR6's target fault (topology double-counting between parallel and consolidated scans) is not involved: base 244 runs consolidated in both runs, and the counts are explained by the bands alone.
