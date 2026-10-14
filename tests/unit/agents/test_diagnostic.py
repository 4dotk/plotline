"""Agent G, the Diagnostic: a short explanation for each flagged month (UI text only).

Offline: the model is a scripted FakeChat. Inputs and outputs are logged.
Goal: an explanation is shown for a flagged month.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from plotline.agents import diagnostic
from plotline.contract import AnomalyFlag, Criteria, TrendRecord, window_months
from plotline.llm_client import LlmClient, LlmSession
from plotline.orchestrator import Engine
from plotline.state import Failure
from plotline.trace import TraceLog
from tests.support import FakeChat, llm_config

log = logging.getLogger("plotline.test.diagnostic")
DATA = Path(os.environ.get("CHENNAI_DATA_DIR", "data"))
MONTHS = window_months("2014-12")
GOOD = json.dumps({"text": "Median price per sqft rose sharply compared with the month before; few sales can exaggerate this."})


def rec(month, count=20, ppsf=8000.0):
    return TrendRecord(month=month, region_key="ALL", listing_count=count, n_in_bucket=count,
                       median_price=ppsf * 1000, median_price_per_sqft=ppsf, low_sample=count < 5,
                       pct_change_price_per_sqft=None)


RECORDS = [rec(m, ppsf=8000.0 if m < MONTHS[5] else 12000.0) for m in MONTHS]
SPIKE = AnomalyFlag(month=MONTHS[5], region_key="ALL", kind="price_jump", value=0.5, threshold=0.12,
                    reason=f"median price per sqft rose 50.0% vs {MONTHS[4]}")
DROP = AnomalyFlag(month=MONTHS[7], region_key="ALL", kind="count_drop", value=0.4, threshold=0.5,
                   reason=f"listing count fell to 8 from 20 in {MONTHS[6]}")


def session(*answers) -> tuple[LlmSession, FakeChat]:
    chat = FakeChat(*answers)
    return LlmClient(llm_config("live"), chat=chat).session(0), chat


class Diagnose(unittest.TestCase):
    def run_diag(self, flags, mode, llm):
        trace = TraceLog()
        log.info("IN   mode=%s flags=%s", mode, [(f.month, f.kind) for f in flags])
        out = diagnostic.diagnose(flags, RECORDS, mode, 0, trace, llm)
        log.info("OUT  %s", out if isinstance(out, Failure) else [(d.month, d.source, d.text) for d in out])
        return out, trace

    def test_off_gives_template_text_and_no_model_call(self):
        llm, chat = session(GOOD)
        out, _ = self.run_diag([SPIKE, DROP], "off", llm)
        self.assertEqual([(d.month, d.source, d.text) for d in out],
                         [(SPIKE.month, "template", SPIKE.reason), (DROP.month, "template", DROP.reason)])
        self.assertEqual(chat.calls, [])

    def test_no_flags_means_no_entries_and_no_call(self):
        llm, chat = session(GOOD)
        out, _ = self.run_diag([], "live", llm)
        self.assertEqual((out, chat.calls), ([], []))

    def test_live_one_entry_and_one_call_per_flag(self):
        llm, chat = session(GOOD)
        out, trace = self.run_diag([SPIKE, DROP], "live", llm)
        self.assertEqual([(d.month, d.source) for d in out], [(SPIKE.month, "llm"), (DROP.month, "llm")])
        self.assertTrue(all(d.text.strip() for d in out))
        self.assertEqual(len(chat.calls), 2)
        self.assertEqual(trace.events, [])  # nothing to warn about

    def test_prompt_figures_come_from_code(self):
        llm, chat = session(GOOD)
        self.run_diag([SPIKE], "live", llm)
        system, user, seed = chat.calls[0]
        payload = json.loads(user)
        self.assertEqual(payload["flag"], {"month": SPIKE.month, "kind": "price_jump", "value": 0.5, "threshold": 0.12})
        self.assertEqual(payload["this_month"]["median_price_per_sqft"], 12000.0)
        self.assertEqual(payload["previous_month"]["month"], MONTHS[4])
        self.assertEqual(payload["previous_month"]["median_price_per_sqft"], 8000.0)
        self.assertIn("Do not invent a cause", system)

    def test_first_month_flag_has_no_previous_month_figures(self):
        llm, chat = session(GOOD)
        flag = SPIKE.model_copy(update={"month": MONTHS[0]})
        self.run_diag([flag], "live", llm)
        self.assertIsNone(json.loads(chat.calls[0][1])["previous_month"])

    def test_malformed_three_times_warns_then_uses_the_template(self):
        llm, chat = session("not json")
        out, trace = self.run_diag([SPIKE], "live", llm)
        self.assertEqual([(d.source, d.text) for d in out], [("template", SPIKE.reason)])
        self.assertEqual(len(chat.calls), 3)
        warnings = [e.msg for e in trace.events if e.kind == "warning" and e.agent == "diagnostic"]
        self.assertEqual(len([w for w in warnings if "attempt" in w]), 3)
        self.assertTrue(any(w.startswith("fallback: template text") for w in warnings))
        self.assertEqual(trace.loop_counters().L1_repairs + trace.loop_counters().L2_attempts, 0)

    def test_empty_extra_or_wrong_type_text_is_malformed(self):
        for bad in ['{"text": ""}', '{"text": "ok", "extra": 1}', '{"text": 5}', '{"words": "x"}', "[]"]:
            with self.subTest(bad=bad):
                llm, _ = session(bad)
                out, _ = self.run_diag([SPIKE], "live", llm)
                self.assertEqual(out[0].source, "template")

    def test_one_bad_flag_does_not_spoil_the_others(self):
        llm, _ = session("nope", "nope", "nope", GOOD)  # flag 1 fails 3 times, flag 2 answers
        out, _ = self.run_diag([SPIKE, DROP], "live", llm)
        self.assertEqual([d.source for d in out], ["template", "llm"])

    def test_unreachable_server_falls_back_to_the_template(self):
        llm, _ = session(ConnectionError("refused"))
        out, trace = self.run_diag([SPIKE], "live", llm)
        self.assertEqual(out[0].source, "template")
        self.assertTrue(any("call failed" in e.msg for e in trace.events))

    def test_replay_miss_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            llm = LlmClient(llm_config("replay", Path(d) / "c.jsonl")).session(0)
            out, _ = self.run_diag([SPIKE], "replay", llm)
        self.assertIsInstance(out, Failure)
        self.assertEqual(out.error.code, "E_REPLAY_MISS")

    def test_inputs_are_not_modified(self):  # I-LLM: only the text of diagnostics
        flags, recs = [SPIKE.model_copy(deep=True)], [r.model_copy(deep=True) for r in RECORDS]
        llm, _ = session(GOOD)
        diagnostic.diagnose(flags, recs, "live", 0, TraceLog(), llm)
        self.assertEqual((flags, recs), ([SPIKE], RECORDS))


@unittest.skipUnless((DATA / "chennai_snapshot.csv").exists(), "snapshot not found (set CHENNAI_DATA_DIR)")
class ShownForAFlaggedMonth(unittest.TestCase):
    """Goal: a fake spike is flagged and the report carries an explanation for that month."""

    CALM = "2014-06"

    @classmethod
    def setUpClass(cls):
        df = pd.read_csv(DATA / "chennai_snapshot.csv")
        cls.df = df.copy()
        in_month = cls.df["sale_date"].str[:7] == cls.CALM
        cls.df.loc[in_month, "price"] = cls.df.loc[in_month, "price"] * 1.5  # fake +50 % spike

    def engine(self, chat=None) -> Engine:
        if chat is None:
            return Engine.from_data_dir(DATA, llm_mode="off")
        return Engine.from_data_dir(DATA, llm_client=LlmClient(llm_config("live"), chat=chat))

    def test_explanation_for_the_spiked_month(self):
        chat = FakeChat(GOOD)
        r = self.engine(chat).run(Criteria(window_end="2015-02"), self.df)
        self.assertEqual(r.status, "ok")
        flagged = {(f.month, f.kind) for f in r.anomaly_flags}
        self.assertIn((self.CALM, "price_jump"), flagged)
        by_month = {}
        for d in r.diagnostics:
            by_month.setdefault(d.month, []).append(d)
        shown = by_month[self.CALM][0]
        log.info("SHOWN %s [%s]: %s", shown.month, shown.source, shown.text)
        self.assertEqual((shown.source, shown.text), ("llm", json.loads(GOOD)["text"]))
        self.assertEqual(len(r.diagnostics), len(r.anomaly_flags))  # one per flag

    def test_only_diagnostics_differ_between_off_and_live(self):  # I-LLM
        off = self.engine().run(Criteria(window_end="2015-02"), self.df)
        live = self.engine(FakeChat(GOOD)).run(Criteria(window_end="2015-02"), self.df)
        keep = lambda r: {k: v for k, v in r.model_dump(mode="json").items() if k not in ("diagnostics", "trace", "metadata")}
        self.assertEqual(keep(off), keep(live))
        self.assertTrue(all(d.source == "template" for d in off.diagnostics))
        self.assertTrue(all(d.source == "llm" for d in live.diagnostics))

    def test_replay_gives_the_same_bytes_as_live(self):  # I-DET
        from plotline.contract import report_to_json
        crit = Criteria(window_end="2015-02")
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "c.jsonl"
            live_client = LlmClient(llm_config("live", cache, cache_write=True), chat=FakeChat(GOOD))
            live = Engine.from_data_dir(DATA, llm_client=live_client).run(crit, self.df)
            engine = Engine.from_data_dir(DATA, llm_client=LlmClient(llm_config("replay", cache)))
            replay, again = engine.run(crit, self.df), engine.run(crit, self.df)
        self.assertEqual(replay.status, "ok")
        self.assertEqual(report_to_json(replay), report_to_json(again))   # I-DET in replay
        self.assertEqual(report_to_json(live).replace('"live"', '"replay"'), report_to_json(replay))
        self.assertTrue(any(d.source == "llm" for d in replay.diagnostics))


if __name__ == "__main__":
    unittest.main()
