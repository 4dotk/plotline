# Execution trace: L1 and L2 firing at run time

*A real run, copied from the application log (`plotline.log`, lines 883–940, 2026-10-16 21:04–21:12). The query was typed into the UI and served by the FastAPI app with the live model (gemma-4-e4b on `llama serve`).*

**Query:** `5bhk flats from 90 to 70 lakhs` · seed 0 · loops on · 7,108 snapshot rows

```
21:04:30  run start: seed=0 llm_mode=live loops_enabled=True input_rows=7108 query='5bhk flats from 90 to 70 lakhs'
 #0  [planner]    warning   attempt 1 of 3: planner call failed: Request timed out.
 #1  [planner]    warning   attempt 2 of 3: planner call failed: Request timed out.
 #2  [planner]    warning   attempt 3 of 3: planner call failed: Request timed out.
 #3  [planner]    warning   fallback: rule-based parser (model output unusable)
 #4  [planner]    step      sentence parsed by the rule-based parser
 #5  [planner]    decision  topology=parallel (7 localities >= 3)
 #6  [scanner]    step      scan: 7 scanner(s), parallel: 0 rows
     [aggregator]           L1 request: fields=['price_band'] issues=['band_inverted']
 #7  [planner]    loop:L1   L1 fired: band_inverted; [9000000,7000000] -> [7000000,9000000]; repair 1 of 2
 #8  [planner]    decision  topology=parallel (7 localities >= 3)
 #9  [scanner]    step      scan: 7 scanner(s), parallel: 63 rows
#10  [aggregator] step      96 buckets (12 months x 8 regions), 63 rows in the window
#11  [validator]  loop:L2   L2 fired: coverage 7/12 below 9/12; widen soft ranges by 20%; attempt 1 of 3
                            data: decided_by=llm, factor=0.2, effective_price_band=[6600000.0, 9400000.0]
#12  [scanner]    step      scan: 7 scanner(s), parallel: 81 rows
#13  [aggregator] step      96 buckets (12 months x 8 regions), 81 rows in the window
#14  [validator]  decision  coverage 10/12 meets 9/12
#15  [anomaly]    step      4 flag(s); summary over 81 rows
     (4 Diagnostic calls to the model, one per flag)
21:12:04  run end: status=ok records=96 flags=4 trace_events=16 L1=1 L2=1
```

## What happens

1. **Model failure is handled, not fatal (#0–#4).** The model server was busy with another job, so the Planner's three attempts timed out and it fell back to the rule-based parser, as the contract requires (`contracts/LLM.md` §8).
2. **Dependency A ⇒ B (#5, #6).** No locality was named, so the Planner chose the parallel topology: 7 scanners, one per locality.
3. **L1, the feedback loop (#6, #7).** The band was written high to low (90 → 70 lakh), so the scan matched 0 rows. The Aggregator sent the criteria back to the Planner (`band_inverted`). The Planner swapped the band, and the pipeline restarted from the scan: 63 rows (#9).
4. **L2, the stop/iterate step (#10–#14).** Only 7 of 12 months had enough sales (`MIN_BUCKET_N` = 5; 9 needed). The Validator's model chose `widen` (`decided_by=llm`). The band was widened by 20 % on each side, to ₹66–94 lakh, from the original values. The rescan found 81 rows, and coverage reached 10/12, so the loop stopped.
5. `loop_counters` = {L1: 1, L2: 1}, equal to the number of `loop` events (invariant I-CAP).

## Why this run mattered

The rule parser **dropped "5bhk"**: it read BHK only when written with a space. So the report answered for every BHK and still came back `ok`. This run is where finding F2 came from (`NOTEBOOK.md`). It led to the parse audit and to agent H, the Inspector, in contract 1.2.0 (`docs/design_changes.md` C22–C23). In the current code:
- H, not the Aggregator, sends the L1 request, before the scan;
- the user also gets `repaired` and `widened` notices;
- "5bhk" would be read as 5 BHK and refused, because the data has 1–4 BHK only.

The loop behaviour shown here (L1 swap, L2 widening from the original band, the caps) is unchanged in 1.2.0.
