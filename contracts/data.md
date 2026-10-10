# DATA SUBCONTRACT — Chennai Housing-Trends Application

**Task:** T75 · **Parent:** `CONTRACT.md` v1.0.0 (the global contract)
**Scope:** data source, cleaning, frozen snapshot, and data-boundary requirements.

This is a **subcontract**, not a separate global or shared contract. It adds detail to sections 3, 4 and 5 of `CONTRACT.md` and MUST NOT contradict or redefine them. If this file and `CONTRACT.md` disagree, `CONTRACT.md` wins and this file is the defect (global "Change rule"). Constants are never defined here; they are imported from `app/contracts.py` (global section 3).

---

## 1. Source

| Item | Value |
|---|---|
| Dataset | Kaggle "Chennai Housing Sales Price", `kaggle.com/datasets/kunwarakash/chennai-housing-sales-price` |
| Raw file | `data/raw/Chennai_Housing_Sale.csv`, committed **unchanged** |
| Raw SHA256 | `f7ba74d1e7aa4f7ad3bd66a8b4b9331d9bc5b8c135213289c4fd8391f6b96a64` |
| Raw rows | 7,109 |
| Coverage | 7 localities, sales from 2004-01 to 2015-02 |
| Licence | Check the licence text on the Kaggle page and cite it in the report (global open item 3). |

The raw file is never read by the application logic or the test suite. It is read only by `scripts/freeze_snapshot.py`.

## 2. Cleaning rules

Applied **once**, by the freeze script, and **never** by the application logic (global 4.2). Rule IDs match the global contract.

| Rule | Action | Rows touched |
|---|---|---|
| R1 | Strip spaces in `AREA`. Map `Chrompt`, `Chrmpet`, `Chormpet` → `Chrompet`; `TNagar` → `T Nagar`; `Karapakam` → `Karapakkam`; `Ana Nagar`, `Ann Nagar` → `Anna Nagar`; `Velchery` → `Velachery`; `Adyr` → `Adyar`; `KKNagar` → `KK Nagar`. | 38 |
| R2 | Strip spaces in `SALE_COND`. Map `Adj Land` → `AdjLand`; `Ab Normal` → `AbNormal`; `Partiall`, `PartiaLl` → `Partial`. | 15 |
| R3 | Drop rows with no `N_BEDROOM`. | 1 |
| R4 | Parse `DATE_SALE` (`dd-mm-yyyy`) to ISO `yyyy-mm-dd`. Stop with an error if any date fails. | 0 failures |
| R5 | Keep only the 7 columns in section 3. Sort by `listing_id`. Write with `\n` line ends, no index. | all |

*Spelling note for the freeze script:* the global contract's R1 list is authoritative for the variants. Where a raw variant differs from the global wording, the script follows the global contract and the audit in `NOTEBOOK.md` (T07).

**Freeze assertions** (script stops on failure): exactly 7 localities; exactly 5 sale conditions; `listing_id` unique; `price` > 0; `sqft` > 0; `bhk` ∈ {1, 2, 3, 4}.

**Every change is logged** by the freeze script (rule ID, row count), so each number in the table above can be reproduced.

## 3. Snapshot

| Item | Value |
|---|---|
| File | `data/chennai_snapshot.csv` — **the only data the application logic and tests read** |
| Rows | 7,108 |
| SHA256 | `18487b6ff164507f254c7bca38f13be786523b1e3fec03dd457bffa866cb6209` |
| Hash file | `data/SNAPSHOT.sha256` — the hash above on one line |

**Columns** (exactly these, in this order, matching global 4.3):

| Column | Type | Meaning | Raw column |
|---|---|---|---|
| `listing_id` | str | Sale id, e.g. `P00001` | `PRT_ID` |
| `locality` | str | One of the 7 canonical names | `AREA` |
| `sqft` | int | Interior area in sq ft | `INT_SQFT` |
| `sale_date` | str | `YYYY-MM-DD` | `DATE_SALE` |
| `bhk` | int | 1–4 | `N_BEDROOM` |
| `sale_cond` | str | `AbNormal`, `AdjLand`, `Family`, `Normal Sale`, `Partial` | `SALE_COND` |
| `price` | int or float | Sale price in `criteria.price_unit`; INR in the snapshot | `SALES_PRICE` |

**Canonical localities (sorted):** `Adyar, Anna Nagar, Chrompet, KK Nagar, Karapakkam, T Nagar, Velachery`.

## 4. Row-drop policy

* **One row is dropped, at freeze time only (D8):** the single row with no bedroom count. 7,109 → 7,108.
* Reason: keeping it with `bhk = null` would break MR10 (additivity over BHK values).
* **No other row is ever dropped, merged or deduplicated**, by the freeze script or by the application (D3, I-NODEDUPE). One row = one sale. Duplicate rows and duplicate `listing_id`s are counted.
* The application logic MUST NOT filter rows for data quality. Only `Criteria` filters (global 5.2) may remove rows, and those are request filters, not cleaning.

## 5. Data-boundary requirements

These bind the application logic and the test suite whenever they touch data (global 4.4, 5.1, 7.2).

1. **Read-only input.** `run(...)` receives `listings_df` with exactly the columns of section 3. A missing column returns `E_SCHEMA`. The application MUST NOT modify `listings_df` (I-PURE); tests build every transformed dataset as a new dataframe.
2. **No I/O inside agents.** No file, network or clock access inside agents (I-CLOCK). "Last year" resolves to the snapshot's latest month, never to today's date.
3. **Month rule.** A sale belongs to the month `sale_date[:7]`. No time zones.
4. **Window.** 12 calendar months ending at `window_end` inclusive (`window_end − 11 … window_end`).
5. **Valid `window_end`:** 2004-12 … 2015-02 (123 values), read from the data, not hard-coded. `GET /api/meta` publishes them. Outside this range → L1 clamp.
6. **Partial months.** 2004-01 and 2015-02 are partial. `metadata.partial_last_month = true` when the window ends at the latest month. The partial month is reported, never "fixed".
7. **Default `window_end`** is the latest month, 2015-02 (D2). It is the one constant `DEFAULT_WINDOW_END`.
8. **No unit conversion** in the application. `price_unit` is a label only (D6). Tests create scaled copies of the data; the application never rescales.
9. **No rounding** of data-derived values anywhere in the application (I-FLOAT).
10. **Price validity.** Rows with a non-finite price or non-positive price/sqft are excluded from medians only (`n_in_bucket`), never from `listing_count`. On the snapshot the two counts are equal.

## 6. Startup integrity check

At start-up the application logic MUST recompute the SHA256 of `data/chennai_snapshot.csv`, compare it to `data/SNAPSHOT.sha256`, and **refuse to run on a mismatch**, returning a report with `status = "error"` and code `E_SNAPSHOT_HASH` (a report, not an exception: I-ERR). The hash is copied into `metadata.snapshot_sha256` of every report and into `results/run_manifest.json`.

## 7. Reproducibility checks

| # | Check | Expected |
|---|---|---|
| RC1 | `python scripts/freeze_snapshot.py data/raw/Chennai_Housing_Sale.csv data/chennai_snapshot.csv` | Prints exactly `18487b6f…b6209`. Deterministic: run twice, same hash. |
| RC2 | SHA256 of the raw file | `f7ba74d1…96a64` |
| RC3 | Row count after freeze | 7,108 |
| RC4 | Snapshot contents | 7 localities, 5 sale conditions, unique `listing_id`, `bhk` ∈ {1–4}, price > 0, sqft > 0, no nulls |
| RC5 | Cleaning counts | R1 = 38, R2 = 15, R3 = 1, R4 = 0 failures |
| RC6 | Golden vectors: `python scripts/golden_vectors.py data/chennai_snapshot.csv 2015-02 2011-12` | Reproduces Appendix A1 (338 rows for 2015-02; 1,300 rows for 2011-12) and the L2 example A3 (38 → 49 → 71 rows; covered months 3 → 6 → 9) |
| RC7 | `python -m tests.reproduce` | Fails loudly on a snapshot hash mismatch; needs no GPU and no network |

A change to the raw file, the freeze script, or any rule in section 2 changes the snapshot hash. That requires a changelog line in `CONTRACT.md` section 12, a version bump, and agreement of both parties before anything else proceeds. After the `v0-results` tag, any such change must also explain what was wrong.

## 8. Traceability to the global contract

| This file | Global contract |
|---|---|
| §1 Source | 4.1 |
| §2 Cleaning rules | 4.2, D8 |
| §3 Snapshot | 4.1, 4.3 |
| §4 Row-drop policy | D3, D8, I-NODEDUPE |
| §5 Data boundaries | 4.4, 5.1, 5.2, D2, D6, I-PURE, I-CLOCK, I-FLOAT |
| §6 Startup check | 4.1, 6.5 (`E_SNAPSHOT_HASH`), I-ERR |
| §7 Reproducibility | 4.1, 9.5, 11, Appendix A |

*Version: 1.0.0 (tracks `CONTRACT.md` v1.0.0). Status: draft, pending agreement at the contract check (T79).*
