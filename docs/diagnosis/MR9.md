# Diagnosis: MR9 in Mode B (paraphrase invariance, live model)

**Class: agent fault (Planner, model reading), triggered by an ambiguous test input. Not fixed (code frozen at 1.2.0).** In the violations the model read "the year to 2010-11" as something other than November 2010. Indian usage also writes the financial year April 2010 – March 2011 as "2010-11". The canonical sentence for the same base names the month in words, so the two readings disagree and MR9 reports it.

## The Nemotron run

MR9 on 30 bases × seeds 0, 101, 202, 5 phrasings per base, on OpenRouter (`nvidia/nemotron-3-super-120b-a12b:free`), 2026-10-17 (`results/mode_b/nemotron/`).

| | |
|---|---|
| Bases violating | 2/30 = 6.7 % [1.8 %, 21.3 %] Wilson |
| Base × seed pairs violating | 2/90 = 2.2 % [0.6 %, 7.7 %] Wilson |
| Skipped | 0 |
| Oracle mismatches | 0 |

The calls were recorded over several sessions into `cache/llm_replay_nemotron.jsonl`. A call already in the cache was answered from it, and only new calls went to the model. So the harness's determinism check (I-DET) here compares replayed answers: its 0 failures say nothing about whether the live model is deterministic. On the 10-base live run it flagged 8 of 10 bases (`docs/report/03_adequacy.md` §5).

## The Gemma run

MR9 was rerun on 30 bases × seeds 0, 101, 202, 5 phrasings per base, on OpenRouter (`google/gemma-4-26b-a4b-it:free`), 2026-10-24/25 (`results/mode_b/gemma26b/mr9/`; cache `cache/llm_replay_gemma26b.jsonl`).

| | |
|---|---|
| Bases violating | **4/30 = 13.3 % [5.3 %, 29.7 %]** Wilson |
| Base × seed pairs violating | **12/90 = 13.3 % [7.8 %, 21.9 %]** Wilson |
| Skipped | 0 |
| Oracle mismatches | 0 |

The four violating bases are exactly the four financial-year-looking dates (9, 10, 22, 24), and all four violate under all three seeds. The failing phrasings are the same two, `phrasing[1]` ("in the year to …") and `phrasing[4]` ("during the year ending …"). In every case the follow-up `window_end` is 2015-02, the latest month, which is what the application uses when the Planner returns no month. The seed no longer decides, so on this model the fault is systematic rather than a sampling accident. The Gemma run also recorded 65 retries, all recovered.

## Evidence (Nemotron run)

**1. The two Nemotron violations** (`violations.csv`): both are seed 101, phrasing 1, field `effective_criteria`, and only `window_end` differs.

| Base | Phrasing 1 (follow-up) | Source `window_end` | Follow-up `window_end` |
|---|---|---|---|
| 10 | "How did flat prices in Velachery, T Nagar, Chrompet or Adyar in the 83.191 to 140.1948 lakh range move in the year to 2010-11?" | 2010-11 | **2011-03** |
| 22 | "How did flat prices in Chrompet or Adyar move in the year to 2010-11?" | 2010-11 | **2015-02** |

The source phrasing of both bases is "… for the 12 months ending November 2010". Localities, price band and BHK were read correctly in both follow-ups.

**2. The model's raw answers** (cache entries `919e74c0245a…` and `02dba9d3209f…`, seed 101):

```
base 10  {"localities": ["Velachery", "T Nagar", "Chrompet", "Adyar"], "window_end": "2011-03", "price_band": [8319100, 14019480], ...}
base 22  {"localities": ["Chrompet", "Adyar"], "window_end": null, ...}
```

* **Base 10:** "2011-03" is the last month of the financial year 2010-11.
* **Base 22:** the model decided that no month was named. It followed the prompt rule "If no month is named, use window_end null" (`src/plotline/prompts/planner.md:16`), and the application then used the default, the latest month in the data (2015-02, D2).

**3. Only the bare `YYYY-MM` after "year to" fails.** Phrasing 1 is the only template that writes the month as `YYYY-MM` after "in the year to". The others say "November 2010", "Nov 2010", "twelve months up to November 2010", or "during the year ending 2010-11". None of them violated on any base or seed on Nemotron; on Gemma, phrasing 4 ("during the year ending …") fails as well.

**4. Only a date that looks like a financial year fails.** A month reads as a financial year when the month number equals the next year's last two digits (2010-**11**, 2007-**08**). 4 of the 30 bases have such a `window_end`:

| Base | `window_end` | Violated on Nemotron |
|---|---|---|
| 9 | 2007-08 | no (all 3 seeds) |
| 10 | 2010-11 | seed 101 |
| 22 | 2010-11 | seed 101 |
| 24 | 2008-09 | no (all 3 seeds) |

Both Nemotron violations fall in these 4 bases, and none in the other 26. On Gemma all 4 violate under all 3 seeds, again none in the other 26. With n = 4 this is suggestive, not significant.

**5. The seed decides on Nemotron.** Seeds 0 and 202 read the same two sentences as 2010-11. At temperature 0 the hosted model still varies by seed on this input, which is the sign of a reading the model is unsure about. On Gemma the seed does not matter: all four bases fail every seed.

## What is not shown

* **Why bases 9 and 24 pass on Nemotron.** The financial-year reading did not occur for 2007-08 or 2008-09 under any seed on that model.
* **Financial year vs copying the prompt example.** The prompt's example is "12 months ending March 2011" → `"2011-03"` (`planner.md:18`), so base 10's answer could also be the example copied. That explains base 10 but not base 22 (null), while the financial-year reading explains both. Separating the two would need about 30 live calls: phrasing 1 with other financial-year-looking months (2012-13, 2013-14, 2005-06) and non-ambiguous controls, under all three seeds. Not run.
* **The model's reasoning.** The Planner runs with thinking on, but the cache keeps only the final answer.

## Classification

**Agent fault in the Planner's reading of the sentence, on an input that is ambiguous in Indian English.**

* **The application:** the model gave a reading that contradicts the canonical sentence for the same base, and nothing caught it. In base 22 the user would get the latest 12 months (to 2015-02) instead of the year to November 2010.
* **The test input:** "the year to 2010-11" is a fair test of robustness, but a human reader in India could also read it as the financial year. A stricter generator would avoid bare `YYYY-MM` where it looks like a financial year.
* **Possible fixes (not applied, code frozen):** a prompt rule saying that `YYYY-MM` such as "2010-11" is a month, never a financial year; or have the Inspector compare the model's `window_end` with the rule parser's reading and notice the disagreement. In Mode A the rule parser reads all 350 bases' phrasings consistently (MR9 0/350).
