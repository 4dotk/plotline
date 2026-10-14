"""Goal: 20 smoke queries parse to valid filters (offline: no server needed).

Three ways through the same Planner, all on the real snapshot:
  * rules only        : the rule-based parser alone gets all 20 right;
  * model, good JSON  : a scripted model answer is validated like a manual filter
                        (bad values go to L1, which repairs them);
  * model, garbage    : the bad output is logged (3 attempts) and the Planner falls
                        back to the rules, so all 20 still end up valid.
The live-model run is scripts/smoke_20_queries.py.
"""

from __future__ import annotations

import logging
import os
import unittest
from pathlib import Path

import pandas as pd

from plotline.agents import nl_rules
from plotline.contract import Criteria
from plotline.llm_client import LlmClient
from plotline.orchestrator import Engine
from plotline.state import DataInfo
from tests.smoke_queries import HARD, QUERIES, SOFT
from tests.support import FakeChat, llm_config

log = logging.getLogger("plotline.test.smoke20")
DATA = Path(os.environ.get("CHENNAI_DATA_DIR", "data"))
SNAPSHOT = DATA / "chennai_snapshot.csv"

# Where the scripted "model" says something invalid on purpose (L1 must repair it).
RAW_MODEL_ANSWER = {
    "Adyar prices up to December 2020": dict(localities=["Adyar"], window_end="2020-12"),
    "Velachery between 90 lakh and 50 lakh last year": dict(localities=["Velachery"], price_band=[9_000_000, 5_000_000]),
    "2 bhk in Velchery last year": dict(localities=["Velchery"], bhk=[2]),
    "Karapakam 1 bhk flats under 50 lakh": dict(localities=["Karapakam"], bhk=[1], price_band=[0, 5_000_000]),
}


def planner_calls(chat: FakeChat, sentence: str) -> int:
    """Planner calls only: the Validator may also ask the model (L2) in live mode."""
    return sum(1 for _system, user, _seed in chat.calls if user.startswith(sentence))


def filters(report) -> dict:
    return {**{k: getattr(report.effective_criteria, k) for k in HARD},
            **{k: getattr(report.criteria_in, k) for k in SOFT}}


@unittest.skipUnless(SNAPSHOT.exists(), "snapshot not found (set CHENNAI_DATA_DIR)")
class SmokeQueries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(SNAPSHOT)
        m = cls.df["sale_date"].str[:7]
        cls.info = DataInfo(first_month=str(m.min()), latest_month=str(m.max()))

    def engine(self, chat=None) -> Engine:
        if chat is None:
            return Engine.from_data_dir(DATA, llm_mode="off")
        return Engine.from_data_dir(DATA, llm_client=LlmClient(llm_config("live"), chat=chat))

    def assert_valid(self, report, sentence):
        self.assertEqual(report.status, "ok", f"{sentence!r}: {report.error}")
        self.assertEqual(report.effective_criteria.domain_violations(), [])

    def test_rules_only_all_20_valid_and_correct(self):
        eng = self.engine()
        for sentence, expected, min_l1 in QUERIES:
            with self.subTest(query=sentence):
                parsed = nl_rules.parse(sentence, self.info)
                log.info("IN   %s", sentence)
                self.assertIsNotNone(parsed)
                r = eng.run(parsed, self.df)
                log.info("OUT  parsed=%s L1=%d", parsed.model_dump_json(exclude_none=True), r.metadata.loop_counters.L1_repairs)
                self.assert_valid(r, sentence)
                self.assertEqual(filters(r), expected)
                self.assertEqual(r.metadata.loop_counters.L1_repairs > 0, min_l1 > 0)

    def test_model_answers_are_validated_like_manual_filters(self):
        for sentence, expected, min_l1 in QUERIES:
            with self.subTest(query=sentence):
                answer = Criteria(**{**expected, **RAW_MODEL_ANSWER.get(sentence, {})}).model_dump_json()
                chat = FakeChat(answer)
                log.info("IN   %s\n     model says %s", sentence, answer)
                r = self.engine(chat).run(sentence, self.df)
                log.info("OUT  status=%s L1=%d effective=%s", r.status, r.metadata.loop_counters.L1_repairs,
                         r.effective_criteria.model_dump_json(exclude_none=True) if r.effective_criteria else None)
                self.assert_valid(r, sentence)
                self.assertEqual(planner_calls(chat, sentence), 1)         # one planner call, no retry
                self.assertTrue(any(e.msg == "sentence parsed by the model" for e in r.trace))
                self.assertEqual(filters(r), expected)
                if sentence in RAW_MODEL_ANSWER:                           # the invalid ones were repaired
                    self.assertGreaterEqual(r.metadata.loop_counters.L1_repairs, 1)

    def test_garbage_from_the_model_is_logged_and_falls_back_to_rules(self):
        for sentence, expected, _ in QUERIES:
            with self.subTest(query=sentence):
                chat = FakeChat("this is not json")
                r = self.engine(chat).run(sentence, self.df)
                warnings = [e.msg for e in r.trace if e.kind == "warning" and e.agent == "planner"]
                log.info("IN   %s\nOUT  warnings=%s", sentence, warnings)
                self.assert_valid(r, sentence)
                self.assertEqual(planner_calls(chat, sentence), 3)         # the model got its retries
                self.assertEqual(len([w for w in warnings if w.startswith("attempt")]), 3)  # bad output is logged
                self.assertIn("fallback: rule-based parser (model output unusable)", warnings)
                self.assertEqual(filters(r), expected)

    def test_unreachable_server_also_falls_back(self):
        chat = FakeChat(ConnectionError("connection refused"))
        r = self.engine(chat).run("2 bhk flats in Anna Nagar last year", self.df)
        self.assert_valid(r, "2 bhk flats in Anna Nagar last year")
        self.assertTrue(any("call failed" in e.msg for e in r.trace if e.kind == "warning"))
        self.assertEqual(r.criteria_in.localities, ["Anna Nagar"])


if __name__ == "__main__":
    unittest.main()
