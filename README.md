# plotline

A multi-agent application that answers a question about Chennai house prices with a 12-month trend, and a metamorphic test campaign for it. The input is structured criteria or one English sentence; the output is a `TrendReport` (medians, counts, month-on-month change, anomaly flags, notices, the full trace). Eight agents run with two loops: L1 repairs bad criteria, L2 widens soft filters when too few months have enough sales. The model never produces a number (D11).

Code and contract are frozen at contract **1.2.0**.

## Installation

Python 3.14 and [uv](https://docs.astral.sh/uv/):

```bash
uv sync
cp .env.example .env    # then edit: model server, LLM_MODE
```

`LLM_MODE` is `live`, `replay` or `off`. With `off` the Planner uses the rule parser, the Validator always widens and the Diagnostic uses templates; no model or network is needed. The tests force `off` (`tests/conftest.py`). `.env.example` describes the local model (Gemma 4 E4B-it, Q4_K_M, `llama serve` on port 8088); `contracts/LLM.md` lists every variable.

## Running

```bash
uv run python -m plotline.api       # FastAPI on 127.0.0.1:8000: GET /api/health, GET /api/meta, POST /api/run
```

Example requests and responses: `examples/`.

## Tests and results

`uv run pytest` is neither Mode A nor Mode B: it runs the unit tests and the harness self-tests, and `tests/conftest.py` forces `LLM_MODE=off` (over `.env` and the command line), so it never reaches a model. Mode A and Mode B are modes of the MT campaign, `tests.mt.run`.

Every MT command below writes into `results/` unless given `--out <dir>`; use `--out` for anything that is not meant to replace the committed results.

| Purpose | Command | Model | Writes to |
|---|---|---|---|
| All unit tests and harness self-tests | `uv run pytest` | off (forced) | `test_logs/` |
| Unit tests only | `uv run pytest tests/unit` | off | `test_logs/` |
| Agent unit tests only | `uv run pytest tests/unit/agents` | off | `test_logs/` |
| Harness self-tests (oracle, statistics, generator, one planted fault per MR) | `uv run pytest tests/mt_selftests` | off | `test_logs/` |
| One file / one test / by name | `uv run pytest tests/unit/agents/test_validator.py`, `…::<test>`, `-k inspector` | off | `test_logs/` |
| Quiet, stop at the first failure | add `-q -o log_cli=false -x` | | |
| **Mode A**, the headline (MR1–MR11, 350 bases, seed 0) | `uv run python -m tests.mt.run --bases 350` | off; MR9 through the rule parser | `results/` |
| Mode A smoke | `uv run python -m tests.mt.run --bases 20 --out <dir>` | off | `<dir>` |
| Mode A, chosen MRs | `uv run python -m tests.mt.run --mr MR3a --mr MR10 --bases 350 --out <dir>` | off | `<dir>` |
| **Mode B**, replayed (reproduces `results/mode_b/openrouter/mr9_30_bases_3_seeds/`) | `LLM_MODE=replay LLM_CACHE_PATH=cache/llm_replay_openrouter.jsonl LLM_MODEL_TAG=nemotron-3-super-120b-openrouter-free LLM_MAX_TOKENS=2048 uv run python -m tests.mt.run --mr MR9 --bases 30 --live --seeds 0 101 202 --out <dir>` | replay, offline | `<dir>` |
| Mode B, live | `uv run python -m tests.mt.run --mr MR9 --bases 30 --live --seeds 0 101 202 --out <dir>` | the model in `.env` | `<dir>` |
| Mutants, all 16 / one | `uv run python -m tests.mt.mutants --bases 60 [--mutant M5] --out <dir>` | off | `results/mutants/` |
| Diagnosis: loops on vs off, trace diff of one base | `uv run python -m tests.mt.diagnose --mr MR10 --base-id 321 --out <dir>` | off | `results/diagnosis/` |
| Diagnosis: MR3 diffs checked against the gate | `uv run python -m tests.mt.diagnose --mr MR3a --explain-gate --out <dir>` | off | `results/diagnosis/` |
| Free text, 34 sentences, rule parser | `uv run python scripts/smoke_20_queries.py --queries tests.nl_eval_queries --rules-only [--out <file>]` | off | `<file>` |
| Free text, 34 sentences, model | `uv run python scripts/smoke_20_queries.py --queries tests.nl_eval_queries [--out <file>]` | `.env` | `<file>` |
| Free text, 18 L1 scenarios, with traces | `uv run python scripts/smoke_20_queries.py --queries tests.nl_l1_scenarios -v` | `.env` | console |
| Coverage by test layer | `uv run python scripts/coverage_by_layer.py --bases 60` | off | `results/adequacy/` |
| Control-flow edges per layer | `uv run python scripts/loop_edges.py --bases 350` | off | `results/adequacy/` |

MR names: `MR1 MR2 MR3a MR3b MR4 MR5 MR6 MR7 MR8 MR9 MR10 MR11`. Mutants: `M1`–`M16`. In the "Writes to" column, a `results/…` default applies when `--out` is left out.

Mode A is deterministic and needs no model or network. Mode B (MR9 on a hosted model, `nvidia/nemotron-3-super-120b-a12b:free` on OpenRouter, 30 bases × seeds 0, 101, 202) can be replayed offline from the committed cache. The cache key includes the model tag and the max tokens, so both must be the recording's (the tag is in the run's manifest; the max tokens were 2048):

```bash
LLM_MODE=replay LLM_CACHE_PATH=cache/llm_replay_openrouter.jsonl \
LLM_MODEL_TAG=nemotron-3-super-120b-openrouter-free LLM_MAX_TOKENS=2048 \
  uv run python -m tests.mt.run --mr MR9 --bases 30 --live --seeds 0 101 202
```

A call missing from the cache fails loudly (`E_REPLAY_MISS`); replay never goes live.

Start with `results/headline_table.md`; `results/README.md` says what every result file is and which command made it.

## Where things are

| Path | What it is |
|---|---|
| `GLOBAL_CONTRACT.md`, `contracts/` | The contract: data, agents, loops, report schema, LLM use, testing protocol; open items in `GLOBAL_CONTRACT.md` §12 |
| `src/plotline/` | The application: `orchestrator.py`, `agents/`, `contract.py` (constants and report models), `api.py` |
| `data/` | Raw Kaggle file, frozen snapshot (`chennai_snapshot.csv`) and its SHA-256, checked on every load |
| `tests/unit/`, `tests/mt_selftests/` | Unit tests; the harness's own tests (oracle, statistics, one planted fault per MR) |
| `tests/mt/` | The MT harness: generator, MRs, independent oracle, mutants, diagnosis |
| `docs/MR_SPEC.md` | Every MR: relation, subdomain, skips, tolerance |
| `docs/report/` | Report: system (01), testing (02), adequacy (03) |
| `docs/diagnosis/` | Root-cause diagnosis of MR3, MR6, MR9, MR10 |
| `docs/design_changes.md` | Every change from the design note, and why |
| `NOTEBOOK.md`, `AI_USE.md` | Lab notebook (predictions, findings F1/F2); how AI tools were used |
