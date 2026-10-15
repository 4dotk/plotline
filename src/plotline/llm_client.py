"""The only module that talks to a model (CONTRACT.md 8, contracts/LLM.md).

One ``LlmClient`` per engine, one ``LlmSession`` per run. A session makes one
logical call per question (``call``): it validates the answer against a
pydantic schema and retries malformed output up to twice. It never writes trace
events itself; it returns the failures and the caller writes the warnings
(LLM.md 10).

Modes (LLM.md 4):
  off     no model, no network; ``call`` returns no value.
  replay  answers from ``cache/llm_replay.jsonl``; a miss is reported, never
          turned into a live call (``E_REPLAY_MISS`` in the caller).
  live    calls the server through LangChain; entries are appended to the
          cache only when ``LLM_CACHE_WRITE=1`` (the canonical machine).

The cache key covers the logical model tag, both prompts, the response schema,
temperature, max tokens, seed and the thinking switch; not the server address or
model name (D10).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ValidationError

from plotline.contract import LLMInfo, LlmMode, canonical_json

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
MAX_ATTEMPTS = 3  # the first attempt plus up to 2 retries (CONTRACT.md 8)
_LIVE_KEYS = ("LLM_BASE_URL", "LLM_MODEL", "LLM_BACKEND", "LLM_BUILD", "LLM_LAUNCH_FLAGS",
              "LLM_GGUF_SHA256", "LLM_QUANT", "LLM_CTX")

Purpose = Literal["planner", "validator", "diagnostic"]
# Model reasoning per use, sent with every request (LLM.md 5). The Planner gains
# accuracy from it; the Validator and Diagnostic answers are short and do not.
THINKING: dict[str, bool] = {"planner": True, "validator": False, "diagnostic": False}
# (system, user, seed, response JSON schema, thinking) -> raw text. Transport
# failures raise ConnectionError or TimeoutError; they count as failed attempts.
ChatFn = Callable[[str, str, int, dict, bool], str]


class LlmConfigError(ValueError):
    """Bad ``.env`` settings: a start-up error, not a domain error."""


def prompt_hash(prompt_dir: Path = PROMPT_DIR) -> str:
    """SHA256 of all prompt files, concatenated in sorted filename order (LLM.md 6)."""
    h = hashlib.sha256()
    for p in sorted(prompt_dir.glob("*.md")):
        h.update(p.read_bytes())
    return h.hexdigest()


def load_prompt(name: str, **values: str) -> str:
    """Prompt file ``prompts/<name>.md`` with ``{placeholders}`` filled from code."""
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8").format(**values)


@dataclass(frozen=True)
class LlmConfig:
    mode: LlmMode = "off"
    model_tag: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.0
    max_tokens: int = 256
    cache_path: Path = Path("cache/llm_replay.jsonl")
    cache_write: bool = False
    backend: str = ""
    build: str = ""
    launch_flags: str = ""
    gguf_sha256: str = ""
    quant: str = ""
    ctx: int = 0

    def __post_init__(self) -> None:
        if self.mode not in ("off", "replay", "live"):
            raise LlmConfigError(f"LLM_MODE must be off, replay or live, got {self.mode!r}")
        if self.temperature != 0:  # LLM.md 3, clarification 1
            raise LlmConfigError(f"LLM_TEMPERATURE must be 0, got {self.temperature}")
        if self.mode != "off" and not self.model_tag:
            raise LlmConfigError("LLM_MODEL_TAG is required in replay and live mode")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "LlmConfig":
        """Read the settings once. With ``env=None`` this loads ``.env`` into the
        process environment first (existing variables win)."""
        if env is None:
            from dotenv import load_dotenv

            load_dotenv(override=False)
            env = dict(os.environ)
        mode = env.get("LLM_MODE", "off").strip().lower()
        if mode == "live":
            missing = [k for k in _LIVE_KEYS if not env.get(k, "").strip()]
            if missing:
                raise LlmConfigError(f"live mode needs these .env keys: {missing}")
        try:
            return cls(
                mode=mode,  # type: ignore[arg-type]
                model_tag=env.get("LLM_MODEL_TAG", "").strip(),
                base_url=env.get("LLM_BASE_URL", "").strip(),
                api_key=env.get("LLM_API_KEY", "").strip(),
                model=env.get("LLM_MODEL", "").strip(),
                temperature=float(env.get("LLM_TEMPERATURE", "0") or 0),
                max_tokens=int(env.get("LLM_MAX_TOKENS", "256") or 256),
                cache_path=Path(env.get("LLM_CACHE_PATH", "") or "cache/llm_replay.jsonl"),
                cache_write=env.get("LLM_CACHE_WRITE", "").strip() == "1",
                backend=env.get("LLM_BACKEND", "").strip(),
                build=env.get("LLM_BUILD", "").strip(),
                launch_flags=env.get("LLM_LAUNCH_FLAGS", "").strip(),
                gguf_sha256=env.get("LLM_GGUF_SHA256", "").strip().lower(),
                quant=env.get("LLM_QUANT", "").strip(),
                ctx=int(env.get("LLM_CTX", "0") or 0),
            )
        except ValueError as exc:
            if isinstance(exc, LlmConfigError):
                raise
            raise LlmConfigError(f"bad LLM setting: {exc}") from exc


@dataclass
class CallOutcome:
    value: BaseModel | None  # schema-valid answer, or None (off, miss, or every attempt malformed)
    failures: list[str] = field(default_factory=list)  # one entry per malformed / failed attempt
    replay_miss: bool = False


def extract_json(text: str) -> str:
    """The JSON object in a model answer, tolerating a surrounding code fence."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the response")
    return cleaned[start : end + 1]


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'root'}: {e['msg']}" for e in exc.errors())
    return str(exc).splitlines()[0] if str(exc) else type(exc).__name__


def retry_suffix(attempt: int, error: str) -> str:
    """Fixed correction text added to the user prompt for a retry (LLM.md 8)."""
    return (
        f"\n\n[retry {attempt}] Your previous answer was invalid: {error}. "
        "Reply with exactly one JSON object that matches the schema, and nothing else."
    )


class LlmClient:
    def __init__(self, config: LlmConfig | None = None, chat: ChatFn | None = None) -> None:
        self.config = config or LlmConfig()
        self._chat = chat
        self._cache: dict[str, dict[str, Any]] | None = None
        self.prompt_hash = prompt_hash()

    @property
    def mode(self) -> LlmMode:
        return self.config.mode

    def session(self, seed: int) -> "LlmSession":
        return LlmSession(self, seed)

    # -- cache ----------------------------------------------------------------

    def cache_key(self, system: str, user: str, schema: dict, seed: int, thinking: bool) -> str:
        c = self.config
        payload = {
            "model_tag": c.model_tag, "system": system, "user": user, "schema": schema,
            "temperature": c.temperature, "max_tokens": c.max_tokens, "seed": seed,
            "thinking": thinking,
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    def _entries(self) -> dict[str, dict[str, Any]]:
        if self._cache is None:
            self._cache = {}
            path = self.config.cache_path
            if path.is_file():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        entry = json.loads(line)
                        self._cache.setdefault(entry["key"], entry)  # first recording wins
        return self._cache

    def _record(self, key: str, raw: str, info: LLMInfo) -> None:
        entry = {"key": key, "raw": raw, "llm": info.model_dump(mode="json")}
        self._entries().setdefault(key, entry)
        if self.config.cache_write:
            path = self.config.cache_path
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")

    # -- raw answers ----------------------------------------------------------

    def live_info(self, seed: int) -> LLMInfo:
        c = self.config
        return LLMInfo(
            backend=c.backend, build=c.build, launch_flags=c.launch_flags,
            gguf_sha256=c.gguf_sha256, quant=c.quant, ctx=c.ctx, temperature=c.temperature,
            seed=seed, prompt_hash=self.prompt_hash,
        )

    def raw_answer(
        self, system: str, user: str, schema: dict, seed: int, thinking: bool,
    ) -> tuple[str, LLMInfo] | None:
        """Raw response text and its run record; None on a replay miss.
        Raises ConnectionError / TimeoutError when a live call fails."""
        key = self.cache_key(system, user, schema, seed, thinking)
        if self.mode == "replay":
            entry = self._entries().get(key)
            if entry is None:
                return None
            return entry["raw"], LLMInfo.model_validate(entry["llm"])
        if self._chat is None:
            self._chat = langchain_chat(self.config)
        raw = self._chat(system, user, seed, schema, thinking)
        info = self.live_info(seed)
        self._record(key, raw, info)
        return raw, info


class LlmSession:
    """The model as seen by one run: it remembers the run record for ``metadata.llm``."""

    def __init__(self, client: LlmClient, seed: int) -> None:
        self.client = client
        self.seed = seed
        self.info: LLMInfo | None = None  # null when no call was made or replayed

    @property
    def mode(self) -> LlmMode:
        return self.client.mode

    def call(self, purpose: Purpose, system: str, user: str, schema: type[BaseModel]) -> CallOutcome:
        if self.mode == "off":
            return CallOutcome(value=None)
        json_schema = schema.model_json_schema()
        out = CallOutcome(value=None)
        prompt = user
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                got = self.client.raw_answer(system, prompt, json_schema, self.seed, THINKING[purpose])
            except (ConnectionError, TimeoutError) as exc:  # not cached; counts as an attempt
                error = f"{purpose} call failed: {_short_error(exc)}"
            else:
                if got is None:
                    out.replay_miss = True
                    return out
                raw, info = got
                if self.info is None:
                    self.info = info
                try:
                    out.value = schema.model_validate_json(extract_json(raw))
                    return out
                except (ValueError, ValidationError) as exc:
                    error = f"malformed {purpose} output: {_short_error(exc)}"
            out.failures.append(f"attempt {attempt} of {MAX_ATTEMPTS}: {error}")
            prompt = user + retry_suffix(attempt, error)
        return out


def langchain_chat(config: LlmConfig) -> ChatFn:
    """Live backend: an OpenAI-compatible server (llama serve, LM Studio) via LangChain.
    Uses a JSON-schema response format when the server accepts it, else plain prompting."""
    import openai
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        base_url=config.base_url, model=config.model, api_key=config.api_key or "not-needed",
        temperature=0, max_tokens=config.max_tokens, timeout=120, max_retries=0,
    )
    use_schema = [True]

    def chat(system: str, user: str, seed: int, schema: dict, thinking: bool) -> str:
        messages = [("system", system), ("human", user)]
        # llama serve hands this to the chat template; servers without it ignore the field
        extra = {"chat_template_kwargs": {"enable_thinking": thinking}}
        try:
            if use_schema[0]:
                fmt = {"type": "json_schema", "json_schema": {"name": "response", "schema": schema}}
                try:
                    resp = llm.invoke(messages, seed=seed, response_format=fmt, extra_body=extra)
                except openai.BadRequestError:
                    use_schema[0] = False  # server has no JSON-schema output: prompt only
                    resp = llm.invoke(messages, seed=seed, extra_body=extra)
            else:
                resp = llm.invoke(messages, seed=seed, extra_body=extra)
        except openai.APITimeoutError as exc:
            raise TimeoutError(str(exc)) from exc
        except openai.APIConnectionError as exc:
            raise ConnectionError(str(exc)) from exc
        return resp.content if isinstance(resp.content, str) else str(resp.content)

    return chat
