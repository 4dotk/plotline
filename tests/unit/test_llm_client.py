import json
import re
import socket
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from plotline.contract import Criteria
from plotline.llm_client import (
    LlmClient,
    LlmConfig,
    LlmConfigError,
    extract_json,
    prompt_hash,
)
from tests.support import FakeChat, llm_config

SRC = Path(__file__).resolve().parents[2] / "src" / "plotline"
GOOD = '{"localities": ["Adyar"], "window_end": "2015-02", "bhk": [1], "price_band": null, "sqft_range": null, "sale_cond": null, "price_unit": "inr"}'


class _NoNetwork:
    """Any socket use inside the block fails the test (replay must never call out)."""

    def __enter__(self):
        self._orig = socket.socket

        def blocked(*a, **k):
            raise AssertionError("network access during replay")

        socket.socket = blocked
        return self

    def __exit__(self, *exc):
        socket.socket = self._orig


class CacheKey(unittest.TestCase):
    def key(self, cfg=None, system="S", user="U", schema=None, seed=0, thinking=False):
        return LlmClient(cfg or llm_config()).cache_key(system, user, schema or {"a": 1, "b": 2}, seed, thinking)

    def test_server_address_and_model_name_are_not_in_the_key(self):  # D10
        base = self.key()
        self.assertEqual(base, self.key(replace(llm_config(), base_url="http://other:9/v1", model="lmstudio-x")))

    def test_every_key_field_changes_the_key(self):
        base = self.key()
        changed = [
            self.key(replace(llm_config(), model_tag="other-tag")),
            self.key(replace(llm_config(), max_tokens=512)),
            self.key(system="S2"), self.key(user="U2"), self.key(schema={"a": 1}), self.key(seed=101),
            self.key(thinking=True),
        ]
        self.assertEqual(len({base, *changed}), 1 + len(changed))

    def test_field_order_does_not_change_the_key(self):  # canonical JSON
        self.assertEqual(self.key(schema={"a": 1, "b": 2}), self.key(schema={"b": 2, "a": 1}))


class Config(unittest.TestCase):
    def test_temperature_must_be_zero(self):
        with self.assertRaises(LlmConfigError):
            LlmConfig.from_env({"LLM_MODE": "off", "LLM_TEMPERATURE": "0.7"})

    def test_off_needs_only_the_mode(self):
        self.assertEqual(LlmConfig.from_env({"LLM_MODE": "off"}).mode, "off")

    def test_live_needs_the_run_record(self):
        with self.assertRaises(LlmConfigError):
            LlmConfig.from_env({"LLM_MODE": "live", "LLM_MODEL_TAG": "t", "LLM_BASE_URL": "http://x/v1"})

    def test_replay_needs_a_model_tag(self):
        with self.assertRaises(LlmConfigError):
            LlmConfig.from_env({"LLM_MODE": "replay"})

    def test_env_example_lists_every_key(self):
        example = (SRC.parent.parent / ".env.example").read_text()
        source = (SRC / "llm_client.py").read_text()
        for key in sorted(set(re.findall(r'"(LLM_[A-Z_]+)"', source))):
            self.assertIn(f"{key}=", example)


class Calls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "llm_replay.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def live(self, *answers, write=True):
        chat = FakeChat(*answers)
        return LlmClient(llm_config("live", self.cache, cache_write=write), chat=chat), chat

    def test_off_never_calls(self):
        chat = FakeChat(GOOD)
        out = LlmClient(LlmConfig(mode="off"), chat=chat).session(0).call("planner", "S", "U", Criteria)
        self.assertEqual((out.value, out.failures, out.replay_miss, chat.calls), (None, [], False, []))

    def test_valid_answer_and_run_record(self):
        client, chat = self.live("```json\n" + GOOD + "\n```")
        s = client.session(7)
        out = s.call("planner", "S", "U", Criteria)
        self.assertEqual(out.value, Criteria(localities=["Adyar"], window_end="2015-02", bhk=[1]))
        self.assertEqual((out.failures, chat.calls[0][2]), ([], 7))
        self.assertEqual((s.info.seed, s.info.prompt_hash, s.info.temperature), (7, prompt_hash(), 0.0))

    def test_thinking_is_set_per_use(self):  # LLM.md 5, v1.1.2
        client, chat = self.live(GOOD)
        s = client.session(0)
        for purpose in ("planner", "validator", "diagnostic"):
            s.call(purpose, "S", f"U-{purpose}", Criteria)
        self.assertEqual(chat.thinking, [True, False, False])

    def test_malformed_kinds(self):
        bad = {
            "non-JSON": "sure, Adyar!",
            "extra field": GOOD[:-1] + ', "city": "Chennai"}',
            "missing/wrong type": '{"bhk": "one"}',
        }
        for name, text in bad.items():
            with self.subTest(name):
                out = LlmClient(llm_config(), chat=FakeChat(text)).session(0).call("planner", "S", "U", Criteria)
                self.assertIsNone(out.value)
                self.assertEqual(len(out.failures), 3)

    def test_unknown_locality_is_not_malformed(self):  # it goes to L1, not to the retry path
        text = GOOD.replace('"Adyar"', '"Adyaar"')
        out = LlmClient(llm_config(), chat=FakeChat(text)).session(0).call("planner", "S", "U", Criteria)
        self.assertEqual((out.value.localities, out.failures), (["Adyaar"], []))

    def test_retry_uses_a_correction_suffix(self):
        client, chat = self.live("nope", GOOD)
        out = client.session(0).call("planner", "S", "U", Criteria)
        self.assertIsNotNone(out.value)
        self.assertEqual(len(out.failures), 1)
        self.assertEqual(chat.calls[0][1], "U")
        self.assertTrue(chat.calls[1][1].startswith("U\n\n[retry 1]"))

    def test_connection_error_is_an_attempt_and_not_cached(self):
        client, _ = self.live(ConnectionError("refused"), GOOD)
        out = client.session(0).call("planner", "S", "U", Criteria)
        self.assertIn("call failed", out.failures[0])
        self.assertEqual(len(self.cache.read_text().splitlines()), 1)  # only the good answer

    def test_cache_written_only_on_the_canonical_machine(self):
        client, _ = self.live(GOOD, write=False)
        client.session(0).call("planner", "S", "U", Criteria)
        self.assertFalse(self.cache.exists())

    def test_replay_reproduces_a_live_retry_chain_without_network(self):
        live, _ = self.live("nope", "still nope", GOOD)
        a = live.session(3)
        out_live = a.call("planner", "S", "U", Criteria)
        replay = LlmClient(llm_config("replay", self.cache))
        with _NoNetwork():
            b = replay.session(3)
            out_replay = b.call("planner", "S", "U", Criteria)
        self.assertEqual((out_replay.value, out_replay.failures), (out_live.value, out_live.failures))
        self.assertEqual(b.info, a.info)  # metadata.llm comes from the cache entry
        entries = [json.loads(line) for line in self.cache.read_text().splitlines()]
        self.assertEqual([e["raw"] for e in entries], ["nope", "still nope", GOOD])

    def test_replay_miss_is_reported_not_called(self):
        with _NoNetwork():
            out = LlmClient(llm_config("replay", self.cache)).session(0).call("planner", "S", "U", Criteria)
        self.assertEqual((out.value, out.replay_miss), (None, True))


class Boundaries(unittest.TestCase):
    def test_only_llm_client_imports_a_model_or_http_library(self):
        pattern = re.compile(r"^\s*(?:from|import)\s+(langchain\w*|openai|httpx|requests|urllib3)\b", re.M)
        offenders = [
            str(p.relative_to(SRC)) for p in SRC.rglob("*.py")
            if p.name != "llm_client.py" and pattern.search(p.read_text())
        ]
        self.assertEqual(offenders, [])

    def test_prompt_hash_follows_prompt_files(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "a.md").write_text("one")
            before = prompt_hash(Path(d))
            Path(d, "a.md").write_text("two")
            self.assertNotEqual(before, prompt_hash(Path(d)))

    def test_extract_json_tolerates_fences(self):
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), '{"a": 1}')
        with self.assertRaises(ValueError):
            extract_json("no object here")


if __name__ == "__main__":
    unittest.main()
