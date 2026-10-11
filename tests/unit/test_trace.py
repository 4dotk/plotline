import unittest

from plotline.contract import TraceEvent
from plotline.trace import TraceLog


class TraceLogTests(unittest.TestCase):
    def test_indices_count_from_zero_without_gaps(self):
        t = TraceLog()
        t.step("planner", "a"); t.decision("planner", "b"); t.warning("scanner", "c"); t.error("reporter", "d")
        self.assertEqual([e.i for e in t.events], [0, 1, 2, 3])
        self.assertEqual([e.kind for e in t.events], ["step", "decision", "warning", "error"])

    def test_l1_event_matches_contract_template(self):
        t = TraceLog()
        ev = t.l1_fired("band_inverted", [9, 1], [1, 9], 1)
        self.assertEqual(ev.msg, "L1 fired: band_inverted; [9,1] -> [1,9]; repair 1 of 2")
        self.assertEqual((ev.agent, ev.kind, ev.loop), ("planner", "loop", "L1"))
        self.assertEqual(set(ev.data), {"issue", "before", "after", "repair_no", "cap"})

    def test_l2_events_follow_l2_widen(self):
        t = TraceLog()
        e1 = t.l2_fired(3, 1, [6600000, 9400000])
        e2 = t.l2_fired(6, 2, [6000000, 10000000])
        e3 = t.l2_fired(7, 3, None, decided_by="llm")
        self.assertEqual(e1.msg, "L2 fired: coverage 3/12 below 9/12; widen soft ranges by 20%; attempt 1 of 3")
        self.assertEqual(e2.msg, "L2 fired: coverage 6/12 below 9/12; widen soft ranges by 50%; attempt 2 of 3")
        self.assertEqual(e3.msg, "L2 fired: coverage 7/12 below 9/12; drop soft filters; attempt 3 of 3")
        self.assertEqual([e.data["factor"] for e in (e1, e2, e3)], [0.2, 0.5, "drop"])
        self.assertEqual(e3.data["decided_by"], "llm")
        self.assertEqual(e1.agent, "validator")

    def test_counters_equal_loop_events_only(self):
        t = TraceLog()
        t.l1_fired("band_inverted", [9, 1], [1, 9], 1)
        t.l2_fired(3, 1, None); t.l2_fired(5, 2, None)
        t.l2_skipped(); t.l2_disabled(); t.l2_stopped_by_model(5)  # never counted
        c = t.loop_counters()
        self.assertEqual((c.L1_repairs, c.L2_attempts), (1, 2))

    def test_non_firing_l2_outcomes(self):
        t = TraceLog()
        s, d, m = t.l2_skipped(), t.l2_disabled(), t.l2_stopped_by_model(4)
        self.assertEqual((s.kind, s.msg), ("decision", "L2 skipped: nothing to widen"))
        self.assertEqual((d.kind, d.msg), ("warning", "L2 disabled"))
        self.assertEqual((m.kind, m.msg), ("decision", "L2 stopped by model: coverage 4/12, need 9/12"))
        self.assertTrue(all(e.loop is None for e in (s, d, m)))

    def test_caps_are_hard(self):
        t = TraceLog()
        with self.assertRaises(ValueError): t.l1_fired("x", 1, 2, 3)
        with self.assertRaises(ValueError): t.l2_fired(1, 4, None)
        with self.assertRaises(ValueError): t.l2_fired(1, 0, None)

    def test_events_are_trace_events_and_copy(self):
        t = TraceLog(); t.step("planner", "x")
        evs = t.events
        self.assertIsInstance(evs[0], TraceEvent)
        evs.clear()
        self.assertEqual(len(t.events), 1)


if __name__ == "__main__":
    unittest.main()
