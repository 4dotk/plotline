# Results

Everything here is generated. Start with **`headline_table.md`**.

## Headline: metamorphic testing, Mode A (model off, 350 bases, seed 0)

Made by `uv run python -m tests.mt.run --bases 350` (one command; deterministic, no model or network needed).

| File | What it is |
|---|---|
| `headline_table.md` | One row per MR: bases evaluated, skips by reason, violation rate with 95 % CI, unconditioned column. **The report's results table.** |
| `violations.csv` | Every conditioned violation (`MR, base_id, seed, field, source_value, follow_up_value`). Empty: 0 violations. |
| `violations_unconditioned.csv` | Diffs inside skipped bases (the unconditioned column), with the skip reason. Input to the diagnosis. |
| `skips.csv` | Every skipped base and why. A skip is not a pass. |
| `bases_and_params.json` | The 350 bases and each MR's drawn parameters, regenerated from `GEN_SEED = 42`. |
| `run_manifest.json` | Snapshot hash, contract version, commit, seeds, counts, invariant and oracle checks, library versions. |

## Folders

| Folder | What it is | Made by | Used in |
|---|---|---|---|
| `mode_b/` | MR9 on the live model (OpenRouter, `nvidia/nemotron-3-super-120b-a12b:free`), 10 bases, seed 0. Same file set as above. | `python -m tests.mt.run --mr MR9 --bases 10 --live` | report part 3 §5 |
| `mode_b/openrouter/` | The same 10 bases and OpenRouter model under seeds 101 and 202 (2026-10-17). With seed 0: k = 3 seeds, 30 seed pairs, 0 violating. | `python -m tests.mt.run --mr MR9 --bases 10 --live --seeds 101 202` | presentation |
| `mode_b/openrouter/replay_3_seeds/` | All three seeds (0, 101, 202) replayed from `cache/llm_replay_openrouter.jsonl`: offline, about 12 s, deterministic (0 I-DET failures). 0/10 bases, 0/30 seed pairs violate. | `LLM_MODE=replay python -m tests.mt.run --mr MR9 --bases 10 --live --seeds 0 101 202` | presentation |
| `mode_b/openrouter/mr9_30_bases_3_seeds/` | MR9 on 30 bases × seeds 0, 101, 202, same OpenRouter model (2026-10-17). 2/30 bases = 6.7 % [1.8 %, 21.3 %], 2/90 seed pairs = 2.2 % [0.6 %, 7.7 %] violate, both under seed 101 (bases 10 and 22: the model read a different `window_end` for phrasing 1). 0 skipped, 0 invariant violations. Base 9 here is not base 9 of the 10-base runs: the phrasings depend on `--bases`. | `python -m tests.mt.run --mr MR9 --bases 30 --live --seeds 0 101 202`, recorded over several sessions into `cache/llm_replay_openrouter.jsonl` and answered from it where a call was already recorded | presentation |
| `diagnosis/` | The three most-violated MRs (MR3, MR10, MR6): each MR with loops on vs off (`*_loops.csv`) and one minimal base's trace (`*_trace.txt`). | `python -m tests.mt.diagnose` | `docs/diagnosis/` |
| `mutants/` | 16 planted bugs and which test layer catches each: `scores.md` (summary), `detection_table.md` (per MR), `detection.json` (raw). | `python -m tests.mt.mutants` | report part 3 §3 |
| `adequacy/` | Code coverage per test layer (`coverage.md`) and the control-flow edges each layer exercises (`loop_edges.md`); `.json` = raw. | `scripts/coverage_by_layer.py`, `scripts/loop_edges.py` | report part 3 §1–2 |
| `nl_eval/` | Free-text sentences through the AI-mode Planner, judged against the expected reading: the 34-sentence set before/after the F2 fixes, for the model and the rule parser alone (`*_before_fixes`, `*_after_fixes`), and the 18 L1 scenarios (`l1_model`, `l1_rules`). | `scripts/smoke_20_queries.py --queries …` | report part 3 §4, `NOTEBOOK.md` F2 |
