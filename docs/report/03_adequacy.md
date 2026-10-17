# Report draft, part 3: how good is the test suite?

*Measured 10-16 and 10-17; the final numbers are on the frozen 1.2.0 code. Every number names its source file. The criteria below were defined after `v0-results`, so they describe the suite; they were not a gate set in advance.*

The suite has four layers:

| Layer | What it is | Size |
|---|---|---|
| Unit tests | `tests/unit`: one file per agent, plus the contract, orchestrator, API and LLM client | 234 tests |
| Harness self-tests | `tests/mt_selftests`: oracle, statistics, generator, and one planted fault per MR | 72 tests |
| MT campaign | `tests/mt/run.py`: MR1–MR11 on 350 bases, Mode A (structured criteria, model off; MR9 through the rule parser), plus MR9 in Mode B on 10 bases | about 7,000 runs before MR11 |
| Free-text sets | `tests/smoke_queries.py` (20), `tests/nl_eval_queries.py` (34), `tests/nl_l1_scenarios.py` (18): sentences through the AI-mode path, judged against an expected reading | 72 sentences |

## 1. Code coverage by layer

Statement / branch coverage of `src/plotline` (`coverage.py --branch`; `results/adequacy/coverage.md`, `scripts/coverage_by_layer.py --bases 60 --live-bases 10`). Three categories:
* **unit**: `tests/unit` plus the 72 free-text sentences (model stubbed);
* **self-tests**: the harness's own tests;
* **MT**: the MR sweep, MR1–MR11 on 60 bases in Mode A, plus MR9 in Mode B on 10 bases with the live model.

*Pipeline* leaves out `api.py` (the web layer, which MT never calls) and `agents/stubs.py` (development scaffolding).

| Category | All of `src/` | Pipeline |
|---|---|---|
| Unit tests (incl. free text) | 95 % / 90 % | 95 % / 91 % |
| Harness self-tests | 72 % / 56 % | 79 % / 60 % |
| MT campaign | **79 % / 62 %** | **86 % / 66 %** |

MT was at **64 % / 39 %** before 10-17. The gain comes from three tests added after measuring: MR11 (L1 repair path), MR9 through the rule parser, and MR9 in Mode B (model path). **Statements are above 70 % in every category; branches are not** (MT 62–66 %, self-tests 56–60 %). The self-tests exist to test the harness, so their coverage of the application is incidental.

Coverage measures which code ran, not which inputs were tried: the BHK pattern line was covered by unit tests while "2bhk" was still dropped (F2).

## 2. Can every loop and branch of the control flow run?

Counted from the trace of every run (`results/adequacy/loop_edges.md`, `scripts/loop_edges.py`). *MT* is 2,718 runs: every source and follow-up of MR1–MR11 on the first 100 bases (MR9 through the rule parser). *Free text* is the 72 sentences with the model stubbed. *Model* is the 86 live-model sentence runs on record, which keep only status, L1 and notices.

| Edge | MT | Free text | Model |
|---|---|---|---|
| L1 fired (any) | 100 | 18 | 10 |
| L1 window_out_of_range | **0** | 10 | – |
| L1 band_inverted / bhk_out_of_range / locality_unknown | 49 / 47 / 100 | 7 / 3 / 0 | – |
| L1 several issues in one pass | 74 | 1 | – |
| L1 cannot repair → error report | 0 | 4 | 5 |
| L2 attempt 1 / 2 / 3 (drop) | 466 / 427 / 376 | 30 / 30 / 29 | – |
| L2 cap reached / nothing to widen | 294 / 97 | 27 / 25 | – |
| L2 stopped by the model | **0** | **0** | – |
| topology parallel / consolidated | 1,463 / 1,255 | 5 / 67 | – |
| notice: repaired / out_of_scope / no_sales / widened / not_read | 196 / 0 / 283 / 466 / 0 | 20 / 4 / 40 / 30 / 2 | 9 / 3 / 10 / 7 / 2 |

* **Before MR11 the MT campaign never ran L1 (0 of 7,059 runs). With it, L1 runs in 100 of 2,718**, including the locality repair, which no layer reached before. MT still never clamps a window (MR11 does not plant one) and never refuses a request.
* **Refusals and out-of-scope notices come only from sentences:** "Hyderabad", "5 BHK", "studio" (free text and model).
* **One edge runs in no counted layer:** the model's L2 `stop` decision. Mode A always widens, and the live-model result files do not keep the trace.
* **The model rarely needs L1.** Before the 1.2.0 prompt it corrected values itself (2 of 68 runs fired L1), so repairs were silent. With the new prompt, L1 fired in 8 of the 18 realistic scenarios (`results/nl_eval/l1_model.jsonl`).

## 3. Mutation score by layer

16 bugs were planted at runtime with `unittest.mock.patch`, so the source files are never edited (`python -m tests.mt.mutants --bases 60 --jobs 8`; `results/mutants/scores.md`, details in `detection_table.md`). M1–M5 are in the Aggregator and Validator; M6–M16 are in the Planner, its rule parser and the Inspector. A layer *kills* a mutant when it reports at least one failure under it.

| Layer | Mutation score | Kills |
|---|---|---|
| Unit tests | **15/16** | all but M16 |
| Free-text sentence sets (rule path, judged against expected readings) | **9/16** | the parser and repair mutants M6–M10, M12, M13; also M1 and M4 |
| MRs + oracle (MT campaign, MR1–MR11) | **4/16** | M2 (mean for median, via MR1's bit-exact check), M3 (order-dependent median: MR1, MR3a/b), M12 (band not swapped) and M15 (repairs not told): both MR11 |
| Contract checks in the application (the run is rejected) | 2/16 | M1, M4 |
| **Any layer** | **15/16** | |

* **MR11 doubled the MT score (2 → 4/16)**, the first MT kills outside the Aggregator. Without MR11 the campaign killed none of the 11 Planner, parser and Inspector mutants.
* **MR9 through the rule parser kills none of the parser mutants (M6–M10).** Its paraphrase templates write prices in lakh only, BHK with a space and "last year" only for the latest month, so a parser bug changes every phrasing the same way and the answers stay equal (`docs/MR_SPEC.md`).
* **The free-text set kills the parser and repair mutants, but none of the notice mutants** (M11, M14, M15). It judges how a sentence was *read*, not what the user is *told*. MR11 catches M15 because it requires a `repaired` notice.
* **M5 (L2 widens one side only) is caught by unit tests alone.** The oracle reads `effective_criteria`, so it cannot see a wrong widening, and every MR skips the bases where L2 fires.
* **M16 survived and is equivalent at the level of results.** With the Inspector's window check off, the Aggregator's own check (kept as a backstop) still sends the request to L1; only the trace order changes.
* *Measurement note:* a first parallel run crashed pytest inside the workers (the test `conftest` recreates one shared log directory per session), which gave false zeros in the unit column. Each worker now gets its own log directory; the counts then match the sequential run. Only the clean run is reported.

## 4. Does it find real faults?

Faults in the application found on 10-16, and the layer that found each one. The MT campaign found none of them.

| Fault | Found by | MT could see it? |
|---|---|---|
| "2bhk" / "5bhk" (no space) dropped: answered for every BHK (F2) | a live UI query; now in the free-text set | No: Mode A never parses sentences |
| Misspellings outside the alias list, "except X", "at least 3 BHK", "for my family" → sale condition Family (F2) | free-text set (rules: 26/34 right before the fixes) | No |
| A place outside the data ("Hyderabad", "Mylapore") answered for all 7 localities | free-text set | No |
| The model dropped "5 BHK", invented a band for "around 80 lakh" (₹75–85 lakh), and obeyed "ignore your instructions" | free-text set, live model (`results/nl_eval/model_before_fixes.jsonl`) | No |
| The model converted "from 1.5 cr down to 90 lakhs" to ₹9 lakh – ₹1.5 crore (90 lakh read as 9 lakh): a number made by the model, which D11 forbids. It also read "big family home" as sale condition Family. 15/18 realistic L1 scenarios right | realistic L1 scenarios, live model (`results/nl_eval/l1_model.jsonl`) | No |
| After the prompt change (10-16) the model still reads "at least 3 BHK" as 3, "for my family" as sale condition Family, and "around 80 lakh" as ₹80–80 lakh: 31/34 right, up from 28/34 | free-text set, live model (`results/nl_eval/model_after_fixes.jsonl`) | No |
| Each locality has its own data range (Adyar ends May 2012): "Adyar 2023", "Adyar 3 BHK" and "Velachery 1 BHK" all returned `ok` with 0 rows and no explanation | realistic L1 scenarios | Partly: such runs were in the sweep, but no MR or oracle check asks whether an empty answer was explained |
| F1: lakh → INR through a float dropped a row at the band edge | code review (10-13) | No |

## 5. How many MRs hold?

Final sweep on the 1.2.0 code (350 bases, seed 0; `results/headline_table.md`). MR1–MR8 and MR10 give the same violations and skips as `v0-results`; only the skip-reason labels differ (all reasons recorded since ab21456). MR9 runs through the rule parser (model stubbed) and MR11 is new.

| MR | Evaluated | Conditioned violations | Unconditioned (diffs inside skips) |
|---|---|---|---|
| MR1, MR2, MR8 | 350 each | 0 | – |
| MR3a, MR3b | 202 | 0 | 142/350 (gate and L2) |
| MR4 | 173 | 0 | – |
| MR5 | 114 | 0 | 13/196 (L2) |
| MR6 | 169 | 0 | 37/226 (L2) |
| MR7 | 266 | 0 | 8/348 (L2) |
| MR9 (rule parser) | 350 | 0 | – |
| MR10 | 154 | 0 | 108/350 (L2) |
| MR11 (repair invariance) | 350 | 0 | – |

**All 12 relations hold:** 0 violations, 0 oracle mismatches, 0 I-DET and I-PURE failures. Every unconditioned diff is explained by L2 or the `MIN_BUCKET_N` gate (`docs/diagnosis/`). Read with sections 1–3: the relations hold, but MR9 (rules) is weak at finding parser faults, and only MR11 reaches the repair path.

**MR9 in Mode B** (live model, nvidia/nemotron-3-super-120b-a12b:free on OpenRouter; 10 bases × 5 phrasings, seed 0; `results/mode_b/`): 0/10 bases violate. That is a 95 % upper bound of 30.8 % (Clopper–Pearson), so it is indicative only; the contract asks for at least 30 bases and 3 seeds (global open item 9). The harness's determinism check flagged 8 of the 10 bases: two live runs of the same input gave different reports. I-DET covers only `off` and `replay`, so this is expected of a live model; what differed was not examined.

**MR9 in Mode B, 30 bases × 3 seeds** (same model, seeds 0, 101, 202; `results/mode_b/openrouter/mr9_30_bases_3_seeds/`): **2/30 bases = 6.7 % [1.8 %, 21.3 %] and 2/90 base × seed pairs = 2.2 % [0.6 %, 7.7 %] violate** (Wilson), 0 skipped, 0 oracle mismatches. This is the first conditioned violation in the campaign. Both are seed 101 on the sentence "… move in the year to 2010-11?": the model returned `window_end` 2011-03 (the end of the Indian financial year 2010-11) for base 10 and null (so the latest month, 2015-02) for base 22, where the canonical sentence says November 2010. Classified as a Planner fault on an ambiguous input, not fixed (`docs/diagnosis/MR9.md`). The calls were answered from the replay cache wherever already recorded, so I-DET here compares replayed answers and does not test live determinism. Still a hosted model, not the canonical machine, and MR1 and MR3 in AI mode were not run (global open item 9).

## 6. What this says about the suite

* **The MT campaign is adequate for the aggregation pipeline and inadequate for the rest.** For C/D/E it shows 0 conditioned violations over about 7,000 runs, kills the order-dependence mutants, and with the oracle cross-checks every number. For the user-facing path, before MR11 and MR9-through-the-parser, it covered 39 % of branches (0 % of the parser), never ran L1, and killed 0 of the 11 Planner, parser and Inspector mutants. This is a design consequence: Mode A sent only valid structured criteria with the model off. With the two additions: 62 % of branches, L1 in 100 of 2,718 runs, 2 of those 11 mutants (both via MR11).
* **The faults that mattered were found by realistic inputs, not by relations.** Every fault in section 4 came from a sentence someone would actually type. A test set of 72 sentences found more application faults than about 7,000 MT runs, because it reached code the campaign could not reach.
* **Unit tests are the strongest single layer (95 % / 90 % coverage, 15/16 mutants),** but they did not find F2 either: they tried the inputs their authors thought of. Coverage and mutation score measure the code under test, not the input space.
* **What we would change:** fix an adequacy criterion before the first run (branch coverage per agent plus a control-flow-edge checklist); run MRs in Mode B on sentences (MR9, plus paraphrase relations such as "2bhk" ≡ "2 BHK"); add the repair-invariance relation from the start (we added MR11 only after measuring) so L1 runs on real data; and judge the notices the user reads, not only the criteria.
