"""MR9 (paraphrases) and MR10 (BHK partition): query file, skips, planted faults."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import pandas as pd

from plotline.agents import default_agents, scanner
from plotline.agents.nl_rules import parse
from plotline.contract import BHK_VALUES, RunOptions
from plotline.orchestrator import Engine
from plotline.state import DataInfo
from tests.mt.generator import SNAPSHOT, generate, valid_window_ends
from tests.mt.harness import frame_hash, rel_tol, report_dict, run_mr
from tests.mt.mrs import MR9, MR10
from tests.mt.mrs.mr09_paraphrase import QUERIES_FILE, mode_b_bases, save_queries, with_phrasings
from tests.support import SNAPSHOT_SHA


def partial_lost_when_split(plan, df, trace):
    """Planted partition fault: a single-BHK request also drops 'Partial' sales."""
    rows = scanner.scan(plan, df, trace)
    bhk = plan.effective.bhk
    return rows[rows["sale_cond"] != "Partial"] if bhk is not None and len(bhk) == 1 else rows


def same_except_band(a, b):
    """Rule-parser output equal, with the band compared by REL_TOL (NOTEBOOK.md finding F1)."""
    da, db = a.model_dump(), b.model_dump()
    ba, bb = da.pop("price_band"), db.pop("price_band")
    return da == db and (ba is None) == (bb is None) and (ba is None or all(map(rel_tol, ba, bb)))


@unittest.skipUnless(SNAPSHOT.is_file(), "frozen snapshot not present")
class MR9Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(SNAPSHOT)
        cls.bases = mode_b_bases(cls.df)
        months = cls.df["sale_date"].str.slice(0, 7)
        cls.info = DataInfo(first_month=months.min(), latest_month=months.max())

    def test_query_set_shape(self):
        latest = valid_window_ends(self.df)[-1]
        self.assertGreaterEqual(len(self.bases), 30)
        self.assertEqual(len({b.canonical for b in self.bases}), len(self.bases))  # distinct bases
        for b in self.bases:
            ph = b.params["MR9"]["phrasings"]
            self.assertGreaterEqual(len(ph) - 1, 4)
            self.assertEqual(len(set(ph)), len(ph))
            self.assertEqual(any("last year" in p for p in ph), b.criteria["window_end"] == latest)
        self.assertGreaterEqual(sum(b.criteria["window_end"] == latest for b in self.bases), len(self.bases) // 5)

    def test_query_file_is_current(self):
        with tempfile.TemporaryDirectory() as d:
            fresh = save_queries(self.bases, Path(d) / "q.json")
            self.assertEqual(json.loads(fresh.read_text()), json.loads(QUERIES_FILE.read_text()))

    def test_every_phrasing_states_the_base(self):
        """Templates sanity: the rule parser reads each phrasing as the base criteria."""
        for b in self.bases:
            for p in b.params["MR9"]["phrasings"]:
                got = parse(p, self.info)
                self.assertTrue(same_except_band(got, b.to_criteria()), (p, got))

    def test_skips_in_mode_a(self):
        engine = Engine(SNAPSHOT_SHA, logic_version="abc1234")
        run = run_mr(MR9, self.bases[:5], self.df, engine.run)
        self.assertEqual({row["reason"] for row in run.skip_rows()}, {"LLM_MODE = off"})
        self.assertEqual(run.result().evaluated, 0)  # a skip is not a pass

    def test_check_compares_criteria_first(self):
        engine = Engine(SNAPSHOT_SHA, logic_version="abc1234")
        src, other = (report_dict(engine.run(b.to_criteria(), self.df, 0, RunOptions())) for b in self.bases[:2])
        diffs = MR9.check(src, [src, other], self.bases[0])
        self.assertEqual([d.field for d in diffs], ["phrasing[2].effective_criteria"])  # nothing else compared

    def test_generic_bases_get_phrasings(self):
        bases = with_phrasings(generate(self.df, 3), self.df)
        self.assertTrue(all(len(b.params["MR9"]["phrasings"]) >= 5 for b in bases))
        self.assertIsNotNone(MR9.precondition(generate(self.df, 1)[0], self.df))


@unittest.skipUnless(SNAPSHOT.is_file(), "frozen snapshot not present")
class MR10Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(SNAPSHOT)
        cls.bases = generate(cls.df, 30)
        cls.engine = Engine(SNAPSHOT_SHA, logic_version="abc1234")

    def test_transformation(self):
        h = frame_hash(self.df)
        for b in self.bases[:6]:
            fus = MR10.transform(b, self.df)
            self.assertEqual([f.query.bhk for f in fus], [[x] for x in (b.criteria["bhk"] or BHK_VALUES)])
            self.assertTrue(all(f.df is not self.df for f in fus))
            others = {k: v for k, v in b.criteria.items() if k != "bhk"}
            self.assertTrue(all({k: v for k, v in f.query.model_dump().items() if k != "bhk"} == others for f in fus))
        self.assertEqual(frame_hash(self.df), h)

    def test_skip_soft_filter(self):
        b = next(b for b in self.bases if b.criteria["price_band"] is not None)
        src = {"effective_criteria": b.criteria, "metadata": {"loop_counters": {"L2_attempts": 0}}}
        self.assertEqual(MR10.skip(src, [src], b), "soft filter set (price_band)")

    def test_application_passes(self):
        run = run_mr(MR10, self.bases, self.df, self.engine.run, check_oracle=True)
        r = run.result()
        self.assertGreater(r.evaluated, 0, r.skipped)
        self.assertEqual((run.invariant_violations, run.oracle_mismatches), ([], []))
        self.assertEqual(r.violations, 0, run.violation_rows()[:3])

    def test_catches_rows_lost_in_the_split(self):
        faulty = Engine(SNAPSHOT_SHA, logic_version="abc1234",
                        agents=replace(default_agents(), scan=partial_lost_when_split))
        run = run_mr(MR10, self.bases, self.df, faulty.run, check_invariants=False)
        self.assertGreater(run.result().violations, run.result().evaluated // 2)  # a single-BHK source is hit too
        self.assertTrue(all(row["field"].endswith(".listing_count") for row in run.violation_rows()))


if __name__ == "__main__":
    unittest.main()
