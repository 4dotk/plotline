import tempfile
import unittest
from pathlib import Path

from plotline.agents import validator
from plotline.contract import Criteria, RunOptions, TrendRecord, window_months
from plotline.llm_client import LlmClient
from plotline.state import Failure
from plotline.trace import TraceLog
from tests.support import FakeChat, llm_config

END = "2010-12"
ORIGINAL = Criteria(localities=["Adyar"], bhk=[1], price_band=[7000000, 9000000], window_end=END)


def records(covered: int) -> list[TrendRecord]:
    """ALL series with ``covered`` months of 5 sales and the rest with 1."""
    out = []
    for i, m in enumerate(window_months(END)):
        n = 5 if i < covered else 1
        out.append(TrendRecord(month=m, region_key="ALL", listing_count=n, n_in_bucket=n, median_price=1.0,
                               median_price_per_sqft=1.0, low_sample=n < 5, pct_change_price_per_sqft=None))
    return out


def run(covered, original=ORIGINAL, attempts=0, options=RunOptions(), llm_mode="off", llm=None):
    trace = TraceLog()
    out = validator.validate(records(covered), original, original, options, attempts, llm_mode, 0, trace, llm)
    return out, trace.events


class Coverage(unittest.TestCase):
    def test_integer_threshold_at_8_9_10(self):
        for covered, fires in ((8, True), (9, False), (10, False)):
            with self.subTest(covered=covered):
                out, _ = run(covered)
                self.assertEqual((out.coverage_months, out.coverage_score), (covered, covered / 12))
                self.assertEqual(out.widen_to is not None, fires)


class Widening(unittest.TestCase):
    def test_steps_measured_from_the_original(self):
        bands = [run(3, attempts=a)[0].widen_to.price_band for a in range(3)]
        self.assertEqual(bands, [[6600000.0, 9400000.0], [6000000.0, 10000000.0], None])

    def test_floor_at_zero_and_sqft_and_sale_cond(self):
        c = Criteria(price_band=[100, 1100], sqft_range=[500, 700], sale_cond=["Family"], window_end=END)
        w = validator.widen(c, 0.5)
        self.assertEqual((w.price_band, w.sqft_range, w.sale_cond), ([0, 1600.0], [400.0, 800.0], ["Family"]))
        d = validator.widen(c, "drop")
        self.assertEqual((d.price_band, d.sqft_range, d.sale_cond, d.localities), (None, None, None, None))

    def test_hard_filters_never_widen(self):
        w = run(3, attempts=2)[0].widen_to
        self.assertEqual((w.localities, w.bhk, w.window_end), (["Adyar"], [1], END))

    def test_loop_event(self):
        _, events = run(3)
        (ev,) = events
        self.assertEqual((ev.agent, ev.kind, ev.loop, ev.data["decided_by"]), ("validator", "loop", "L2", "rule"))
        self.assertEqual(ev.msg, "L2 fired: coverage 3/12 below 9/12; widen soft ranges by 20%; attempt 1 of 3")


class NoFiring(unittest.TestCase):
    def test_cap_reached(self):
        out, events = run(3, attempts=3)
        self.assertIsNone(out.widen_to)
        self.assertEqual([e.kind for e in events], ["decision"])

    def test_skipped_without_soft_filters(self):
        out, events = run(3, original=Criteria(localities=["Adyar"], window_end=END))
        self.assertIsNone(out.widen_to)
        self.assertEqual([(e.kind, e.msg) for e in events], [("decision", "L2 skipped: nothing to widen")])

    def test_disabled(self):
        out, events = run(3, options=RunOptions(loops_enabled=False))
        self.assertIsNone(out.widen_to)
        self.assertEqual([(e.kind, e.msg) for e in events], [("warning", "L2 disabled")])


class Model(unittest.TestCase):
    def session(self, *answers):
        chat = FakeChat(*answers)
        return LlmClient(llm_config("live"), chat=chat).session(0), chat

    def test_no_call_when_off_or_when_l2_cannot_fire(self):
        s, chat = self.session('{"action": "stop"}')
        run(10, llm_mode="live", llm=s)
        run(3, attempts=3, llm_mode="live", llm=s)
        run(3, options=RunOptions(loops_enabled=False), llm_mode="live", llm=s)
        self.assertEqual(chat.calls, [])

    def test_model_widen(self):
        s, _ = self.session('{"action": "widen"}')
        out, events = run(3, llm_mode="live", llm=s)
        self.assertIsNotNone(out.widen_to)
        self.assertEqual(events[-1].data["decided_by"], "llm")

    def test_model_stop_is_a_decision_not_a_firing(self):
        s, _ = self.session('{"action": "stop"}')
        out, events = run(3, llm_mode="live", llm=s)
        self.assertIsNone(out.widen_to)
        self.assertEqual([(e.kind, e.loop) for e in events], [("decision", None)])
        self.assertEqual(events[0].msg, "L2 stopped by model: coverage 3/12, need 9/12")

    def test_malformed_falls_back_to_the_rule(self):
        s, chat = self.session('{"action": "maybe"}')
        out, events = run(3, llm_mode="live", llm=s)
        self.assertEqual(len(chat.calls), 3)
        self.assertEqual([e.kind for e in events], ["warning"] * 4 + ["loop"])
        self.assertEqual(events[-1].data["decided_by"], "rule")

    def test_replay_miss(self):
        with tempfile.TemporaryDirectory() as d:
            s = LlmClient(llm_config("replay", Path(d) / "c.jsonl")).session(0)
            out, _ = run(3, llm_mode="replay", llm=s)
        self.assertEqual((type(out), out.error.code), (Failure, "E_REPLAY_MISS"))

    def test_prompt_holds_counts_and_names_only(self):  # LLM.md 6
        s, chat = self.session('{"action": "widen"}')
        run(3, llm_mode="live", llm=s)
        system, user, _ = chat.calls[0]
        self.assertEqual(user, '{"attempt":1,"cap":3,"coverage_months":3,"need_months":9,'
                               '"next_factor":0.2,"soft_filters":["price_band"]}')
        for value in ("7000000", "9000000", "Adyar", "2010"):
            self.assertNotIn(value, system + user)


if __name__ == "__main__":
    unittest.main()
