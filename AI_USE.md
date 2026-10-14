# AI use

How we used AI tools to build this project, what each did, how we checked it, and where it was wrong. The dated log of mistakes is in `NOTEBOOK.md`; the cases are summarised in section 5.

## 1. Tools

| Tool | Model | Used for |
|---|---|---|
| Claude (Anthropic), in Claude Code | Claude | Code, subcontracts, tests; review and correction of other tools' output |
| pi (agent harness), via OpenRouter | NVIDIA Nemotron Super 120B | Code |
| Lovable | its base free model | The UI |
| Gemma 4 E4B-it (4 billion parameters), Q4_K_M GGUF | the model inside the application | Part of the product, not a development tool (section 3) |

Code was written by Claude and by Nemotron. Everything was reviewed and corrected by Claude and by the two of us.

## 2. What the AI tools did

**Claude**
- Wrote the four subcontracts (data, agents, testing, LLM) from the global contract. Our later versions of the contracts replaced them.
- Implemented the runtime schemas (`src/plotline/contract.py`) from the contract.
- Wrote the orchestrator skeleton, the trace logger and a stub engine that returns a contract-shaped report, with tests.
- Reviewed the L1 repair loop and added case-insensitive locality matching with tests.
- Wrote the test that inserts a fake price spike and checks it is flagged with a reason.
- Wrote the 20-query smoke script for the AI Planner, with expected filters and offline tests.
- Wrote the Diagnostic agent (model text, template fallback), its prompt, its tests and a demo script.
- Helped set up the local model server configuration (`.env`).
- Checked `NOTEBOOK.md` against the result files: re-ran the full sweep, which reproduced byte-identically, and found that the MR3 count differences come from L2, not the gate.

**Nemotron (through pi)**
- Wrote code, including first versions of the adapter and of MR2 and MR8. Those were discarded or fixed by hand (section 5).

**Lovable**
- Built the UI against `example_response.json`.

**What the AI did not decide**
- The requirements, the contract decisions (D1 to D11), the choice of metamorphic relations and the predictions.
- Any number in a report. Every number is computed by code; the model in the product only writes words and chooses between two options (section 3).

## 3. The model inside the application

The application uses one local model, **Gemma 4 E4B-it** (4 billion parameters), quantised to Q4_K_M (GGUF from `unsloth/gemma-4-E4B-it-GGUF`, SHA256 `85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87`). It is served by `llama serve` on the canonical machine and by LM Studio on the second machine, through one OpenAI-compatible endpoint. It is reached only through `src/plotline/llm_client.py`.

It has three jobs (global contract D11, I-LLM):
1. **Planner (AI mode):** turn a sentence into `Criteria`. If its output is malformed after retries, a rule-based parser takes over.
2. **Validator (L2):** choose `widen` or `stop`. Its prompt contains counts and filter names only, never a price, sqft or locality value. With the model off, the rule is `widen`.
3. **Diagnostic:** write a short explanation for each flagged month, for the UI only. The template text is used if the model fails.

Temperature is 0 and every answer is checked against a pydantic schema. Modes are `live`, `replay` (answers from a committed cache, no model and no network) and `off`. With `off` or `replay`, the same input gives a byte-identical report (I-DET). No test of a numeric field calls the model.

## 4. How we checked AI output

- **Contract first.** `GLOBAL_CONTRACT.md` and the subcontracts are the source of truth. Code and tests were checked against them, and a disagreement is treated as a defect.
- **Independent oracle.** `tests/mt/oracle.py` re-implements the report formulas in plain pandas without importing application logic. The application is compared to it on every base.
- **Metamorphic tests.** MR1 to MR10, run on 350 base inputs in Mode A. Every MR has its own tests. Most have a planted-fault selftest, which injects a known bug and checks that the MR fails on it. A check that cannot fail does not count.
- **Unit tests** for every agent, the trace, the contract models and the LLM client. Tests log their inputs and outputs.
- **Free invariants on every base:** determinism (I-DET) and no modification of inputs (I-PURE).
- **Reproduction.** The snapshot rebuilds from the raw file to the contract hash, and a re-run of the full sweep reproduces the committed results exactly.

## 5. Where the tools were wrong

The dated log is in `NOTEBOOK.md`. In summary:

**Nemotron / pi**
- It wrote an adapter in `src/plotline` instead of an implementation. We fixed it by hand.
- Its MR2 and MR8 checks read top-level report fields that do not exist, so they could never fail. We discarded them and rewrote MR2 to MR10, most with a planted-fault selftest, so a check that never fails is caught.

**Claude**
- It put owners into contracts, which a contract must not contain. We caught this in review, and the owners were removed from all four subcontracts.
- `TraceLog.l2_fired` silently used the wrong widening factor for attempt 0. Its own tests caught this, and it now raises an error for any attempt outside 1 to 3.
- It first named the schema module `app/contracts.py`; the contract says `contract.py`. It was renamed when the code was aligned with contract v1.1.0.
- It wrote a test window that fell outside the valid range of the data, and a fake validator whose coverage did not match its records. The strict report validator rejected both.
- It wrote its own L1 repair module without seeing the repository's planner, which already implemented the loop. The duplicate was dropped once the real project was shared and the existing code was reviewed instead.
