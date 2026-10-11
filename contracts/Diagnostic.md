# Agent G — Diagnostic

*Shard of `agents.md` v1.1.0. Read **this file and `_common.md` only**. `CONTRACT.md` wins on any conflict.*

**Kind:** text writer (model, template fallback)

**Constants** (reading only; import from `app/contract.py`, never retype): (none; model retries = 2, set in llm_client)

**Types:** `from app.contract import AnomalyFlag, TrendRecord, Diagnostic`


**Job:** write a short plain-language reason for each flag. **LLM:** yes (template if `LLM_MODE=off`).

| | |
|---|---|
| **Inputs** | `anomaly_flags`, `records` (read-only, for the figures in the prompt), `llm_mode`, `seed`. |
| **Outputs** | `diagnostics`: a list of `{month, text, source}`, `source` ∈ {`llm`, `template`}. |
| **May change** | `diagnostics` only (I-LLM). |

**Does**
* One entry per flag (none when there are no flags, and then **no LLM call**).
* `LLM_MODE=off` → deterministic template text, `source = "template"`.
* `LLM_MODE` ∈ {live, replay} → ask through `llm_client` (temperature 0, JSON checked with pydantic, prompts in `app/prompts/*.md`). Malformed output → one `warning` trace event per failure, up to 2 retries, then the **template** text for that flag. Each fallback is logged.
* The numbers the model sees are passed in from code. The model may only change the **text**.

**Must not:** change any numeric field, add or remove a flag, change `status`, `records`, `summary` or `coverage_score`, or import an HTTP or LLM library (only `llm_client.py` does).

**Failure behaviour:** malformed LLM output never fails the run (template fallback). `LLM_MODE=replay` with an uncached prompt → `E_REPLAY_MISS` **[clarification, listed in `_review.md`]**.

## Tests for this agent

Template when off; one entry per flag; no entries and no LLM call when no flags; malformed output → warning, retries, template; only `diagnostics` differs between modes
