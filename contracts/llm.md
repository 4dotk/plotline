# LLM SUBCONTRACT — Chennai Housing-Trends Application

**Task:** T78 · **Parent:** `CONTRACT.md` v1.0.0 (the global contract)
**Scope:** model configuration, modes (live, replay, off), cache, seeds and settings, output validation, retries, fallbacks, and logging.

This is a **subcontract**, not a separate global or shared contract. It is derived from `CONTRACT.md` sections 5.4, 6.4, 6.5, 7.1, 7.2 and 8 and MUST NOT contradict or redefine them. If this file and `CONTRACT.md` disagree, `CONTRACT.md` wins and this file is the defect. Constants come from `app/contracts.py` (global section 3). Numbers quoted below are for reading only.

Where this file adds a detail the global contract leaves open, the line is marked **[clarification]** and listed in section 12 for the T79 contract check.

---

## 1. Where the model is used and what it may change

* The model is used in **two places only**: the Query Planner in AI mode (sentence → `Criteria`) and the Diagnostic agent (text for each anomaly flag). No other agent calls it.
* **I-LLM:** the model can change only (a) which `Criteria` the Planner produces in AI mode and (b) the text in `diagnostics`. **Every number in the report comes from code.** Once the Planner has produced a `Criteria`, everything downstream is deterministic.
* Structured mode (a `Criteria` as input) makes no Planner call. A run with no anomaly flags makes no Diagnostic call.

## 2. One module, one function

* Exactly **one module**, `app/llm_client.py`, may talk to a model. No other module imports an HTTP library, an LLM SDK, or LangChain for this purpose. This is checked by a test (section 11).
* The client exposes one call that takes: a purpose (`planner` or `diagnostic`), a system prompt, a user prompt, a response schema, and a seed. It returns either schema-valid JSON or a failure result that the caller handles (section 8).
* The same call works in all three modes and against any backend (`llama serve`, LM Studio). **Callers see no difference.** No server name, address or model name appears in code.
* LangChain, if used, is an implementation detail inside this module only.

## 3. Configuration

All settings come from `.env` (read once by the config loader). Commit `.env.example`; never commit `.env`.

| Key | Meaning |
|---|---|
| `LLM_MODE` | `live`, `replay` (default for reproduction) or `off` |
| `LLM_BASE_URL`, `LLM_API_KEY` | Server address and key (local servers accept any key) |
| `LLM_MODEL` | The server's own model name; differs between LM Studio and `llama serve` |
| `LLM_MODEL_TAG` | **Logical** name used in cache keys; identical on every machine, e.g. `gemma-4-e4b-<quant>` |
| `LLM_TEMPERATURE`, `LLM_MAX_TOKENS` | Sampling settings, fixed for all runs |
| `LLM_SEED` | Default seed when a run is started without one |

* **Temperature is 0** for every run (global section 8). A different `LLM_TEMPERATURE` is rejected by the loader at start-up. **[clarification]**
* `LLM_MODE=off` needs no other key. `live` and `replay` need the keys above (`LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL` are used only by `live`).
* Context size and GPU settings are **not** in `.env`: they are set when the server starts and are recorded in the README and in `metadata.llm` (section 10).
* **The seed.** The seed that reaches the client is the `seed` argument of `run` (global 5.1). `LLM_SEED` supplies the value when a caller (API or command line) gives none. The seed actually used goes into the cache key and into `metadata.seed`. With `LLM_MODE=off` the seed changes nothing. **[clarification]**
* **Model identity.** `LLM_MODEL_TAG` must change whenever the GGUF file or its quantisation changes, so two different files can never share cache entries. Both machines should use the same GGUF; if they differ, write it down (it is a threat to validity).

## 4. Modes

| | `off` | `replay` | `live` |
|---|---|---|---|
| Model or network call | never | never | yes |
| Planner, AI mode | `E_LLM_OFF` | answer from cache | call the model |
| Planner, structured mode | no call | no call | no call |
| Diagnostic | template text, `source = "template"` | answer from cache | call the model |
| Cache miss | not applicable | `E_REPLAY_MISS`, **never** a silent live call | not applicable (the call is made) |
| Report bytes | identical for identical input (I-DET) | identical for identical input (I-DET) | may drift |
| `metadata.llm` | `null` | the recorded values from the cache entries used (`null` if none used) | recorded values of the live call (`null` if none made) |

* In `off` and `replay`, the same (`query`, `listings_df`, `seed`, `options`) gives a **byte-identical JSON report** (I-DET). `metadata.llm` is therefore taken from the cache entry, not from the current machine.
* `replay` needs no GPU and no network.
* The report states that a live run may drift.

## 5. Cache

**File:** `cache/llm_replay.jsonl`, committed. Only the canonical machine writes it. A live run on another machine must not modify the committed file. **[clarification]**

**Key** = SHA256 of the canonical JSON of:

`{ LLM_MODEL_TAG, system prompt, user prompt, response schema, temperature, max tokens, seed }`

* Canonical JSON: keys sorted at every level, no whitespace, UTF-8, numbers in shortest round-trip form. **[clarification]**
* The server address and the server's model name are **not** in the key (D10).
* Changing any one of the seven fields gives a different key.

**Entry** (one JSON object per line) holds the `key`, the model's **raw response text**, and the recorded `llm` metadata of the live call that produced it (section 10). **[clarification]**

* Raw text is stored for **every** call, including responses that later fail validation. Validation runs again on replay, so a retry chain and a fallback replay exactly as they happened live.
* A call that fails before a response exists (connection error, timeout) is **not** cached.
* A cache entry is never edited by hand.
* Editing a prompt file changes the system or user prompt and so changes the key. Affected entries must be re-recorded on the canonical machine; until then replay reports `E_REPLAY_MISS` (loudly, as intended).

## 6. Prompts

* Prompts live in `app/prompts/*.md`, one file per purpose.
* `metadata.llm.prompt_hash` is the SHA256 of the contents of all prompt files, concatenated in sorted filename order. **[clarification]**
* A prompt contains only data passed in from code (the sentence, or the flag and its figures). Nothing in a prompt asks the model to compute a number that ends up in the report.

## 7. Output validation

* Output is JSON checked with **pydantic** against the response schema. Output is **malformed** when it is not parseable JSON or fails the schema (wrong type, missing field, extra field).
* **Planner schema:** exactly the fields of `Criteria` (global 5.2) and nothing else. Extra fields are malformed.
* **Diagnostic schema:** one JSON object with a single non-empty `text` string (one call per flag).
* **Schema validity is not criteria validity.** A well-formed `Criteria` with an unknown locality, an inverted band or an out-of-range window is **not** malformed: it goes to the L1 repair loop (global 7.3), not to the retry path here.
* **Constrained output.** Where the server supports a JSON-schema response format, the client uses it. If `llama serve` does not expose it (global section 8, not yet verified), the client falls back to "prompt for JSON, validate, retry". Callers see no difference.

## 8. Retries and fallback

| Situation | Behaviour |
|---|---|
| Malformed output | One `warning` trace event for that attempt, then retry. At most **2 retries** (3 attempts in all). |
| Still malformed after the retries, Planner | Fall back to the **rule-based Planner**. Fallback logged. If the rule-based parser fails too → `E_NL_UNPARSEABLE`. |
| Still malformed after the retries, Diagnostic | Use the **template** text for that flag, `source = "template"`. Fallback logged. |
| Connection error or timeout (live) | Counts as a failed attempt (not cached); same retry and fallback path. **[clarification]** |
| `LLM_MODE=off`, Planner in AI mode | `E_LLM_OFF` |
| `LLM_MODE=replay`, key not in the cache | `E_REPLAY_MISS`. Never a live call. This applies to the Diagnostic as well as the Planner. **[clarification]** |

* **Retry prompt.** At temperature 0 with the same seed, repeating an identical prompt would return the same text. A retry therefore uses the original prompts plus a fixed correction suffix that names the validation error and the attempt number. The suffix changes the user prompt and so the key; it replays like any other call. **[clarification]**
* **Each fallback is logged** as a `warning` trace event naming the agent and the reason. Retries and fallbacks are **not** loop firings and never count in `loop_counters`.
* A fallback never changes the contract: the rule-based Planner and the template produce the same fields as the model path.
* The Diagnostic never blocks a report: malformed output ends in a template, not an error. Only `E_REPLAY_MISS` can fail a run from this module.

## 9. Determinism and independence

* With `LLM_MODE` ∈ {off, replay}, no wall-clock time, random number or server detail enters the report (I-DET, I-CLOCK). Timing and raw call logs, if kept, live outside the report.
* The model's only randomness control is `seed` (global 5.1). Outside this module there are no random numbers.
* The model is never called in a test of a numeric field: tests of the Planner's paraphrase behaviour (MR9) and of AI-mode MR1 and MR3 run in Mode B (live on the canonical machine, then replayed).

## 10. Logging and metadata

* Every run that made or replayed a model call records `metadata.llm = { backend, build, launch_flags, gguf_sha256, quant, ctx, temperature, seed, prompt_hash }` (global 6.4). It is `null` when no model call was made or replayed.
* `backend` and `build` name the server and its version (`llama serve` build, LM Studio version). `launch_flags` and `ctx` are the server's start-up settings. `gguf_sha256` is the hash of the main `.gguf` file only. `quant` is the quantisation.
* The `llama` build is frozen after Day 1; updating it is banned. A new build means a new run record, and the cache entries from the old build are not mixed in.
* A **live** run writes these values from the config and the server it called. A **replay** run reports the values stored with the cache entries it used.
* Settings (`LLM_MODE` and the keys in section 3) are also recorded in `results/run_manifest.json` (global section 11).
* Trace events written by this module's callers: one `warning` per malformed attempt; one `warning` per fallback. No event is written for a successful first attempt beyond the agent's normal `step`.

## 11. Tests (what must exist)

| Test | Expectation |
|---|---|
| Same call in three modes | Returns the same shape in `off`, `replay`, `live`; no server name in code |
| No other module talks to a model | Static check: only `app/llm_client.py` imports an HTTP library, SDK, or LangChain |
| Cache key content | Changing `LLM_BASE_URL` or `LLM_MODEL` keeps the same key (hit). Changing `LLM_MODEL_TAG`, either prompt, the schema, temperature, max tokens or seed changes the key |
| Canonical JSON | Same fields in a different order give the same key |
| Replay miss | `E_REPLAY_MISS`; sockets blocked in the test prove no network call |
| Off mode | No client call; AI mode → `E_LLM_OFF`; Diagnostic uses the template |
| Validation | Extra field, missing field, wrong type and non-JSON are all malformed; an unknown locality is **not** malformed |
| Retry and fallback | Malformed ×3 → 3 `warning` events plus a fallback event; Planner falls back to the rule parser; Diagnostic to the template; `loop_counters` unchanged |
| Retry replay | A recorded retry chain replays to the same fallback with no live call |
| Determinism | Two replay runs of the same input give byte-identical JSON, including `metadata.llm` |
| I-LLM | Between modes, only `diagnostics` (and, in AI mode, `effective_criteria`) may differ |
| Prompt hash | Editing any prompt file changes `prompt_hash` and causes a replay miss |
| Config | `.env` is ignored by version control; `.env.example` lists every key; `LLM_TEMPERATURE` ≠ 0 is rejected; `off` runs with only `LLM_MODE` set |

## 12. Clarifications this file adds (review at T79)

| # | Point | What this file says | Why it needs a look |
|---|---|---|---|
| 1 | Temperature | Loader rejects any value other than 0 | Global says "Temperature 0" and "fixed values for all runs", but also lists `LLM_TEMPERATURE` as a setting |
| 2 | `LLM_SEED` vs `run(seed)` | `run`'s `seed` argument wins; `LLM_SEED` fills in when none is given | Global `run` has `seed: int = 0`, which would make a default always present |
| 3 | Who writes the cache | A live run elsewhere must not modify the committed file | Global names the canonical machine but not how others avoid writing |
| 4 | Canonical JSON and entry format | Sorted keys, compact, UTF-8; entry = key, raw text, recorded `llm` metadata | Global names the key fields, not the serialisation or the entry |
| 5 | Retry meaning | Retry uses a fixed correction suffix, since an identical prompt would repeat the output at temperature 0 | Global says "up to 2 retries" without saying what changes |
| 6 | Warnings | One `warning` per malformed attempt, plus one for each fallback | Global says "one warning trace event" for malformed output; per attempt versus per chain is open |
| 7 | Connection errors | Count as a failed attempt, not cached | Global lists no error code for an unreachable server |
| 8 | `E_REPLAY_MISS` in the Diagnostic | Fails the whole report, never a live call | Could instead fall back to the template; the agents subcontract flags the same question |
| 9 | `prompt_hash` | SHA256 over all prompt files, concatenated in sorted filename order | Global says only "their hash" |
| 10 | `metadata.llm` in replay | Taken from the cache entry | Needed for I-DET to hold across machines; global does not say |

## 13. Traceability to the global contract

| This file | Global contract |
|---|---|
| §1 Use and limits | 7.1, I-LLM |
| §2 One module | 8 |
| §3 Configuration | 8 (`.env` keys), 5.1, D10 |
| §4 Modes | 5.4, 6.5 (`E_LLM_OFF`, `E_REPLAY_MISS`), 7.2 (I-DET), 8 |
| §5 Cache | 8, D10 |
| §6 Prompts | 8, 6.4 |
| §7 Validation | 8, 5.4, 7.3 (L1) |
| §8 Retries and fallback | 8, 5.4, 6.5 (`E_NL_UNPARSEABLE`), 7.4 |
| §9 Determinism | 7.2 (I-DET, I-CLOCK), 9.4 |
| §10 Logging and metadata | 6.4, 8, 11 |
| §11 Tests | 9, 8 |

*Version: 1.0.0 (tracks `CONTRACT.md` v1.0.0). Status: draft, pending agreement at the contract check (T79).*
