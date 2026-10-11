"""The UI example files stay contract-valid and in step with the API."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from plotline.api import create_app
from plotline.contract import TrendReport

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"


class ExampleFiles(unittest.TestCase):
    def report(self, name):
        return TrendReport.model_validate_json((EX / name).read_text(encoding="utf-8"))

    def test_ok_example_matches_golden_a1(self):
        r = self.report("example_response.json")
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.summary.n_rows, 338)
        self.assertEqual([(f.month, f.kind) for f in r.anomaly_flags],
                         [("2014-12", "price_jump"), ("2015-01", "price_jump")])

    def test_loops_example_shows_both_loops(self):
        r = self.report("example_response_loops.json")
        self.assertEqual((r.metadata.loop_counters.L1_repairs, r.metadata.loop_counters.L2_attempts), (1, 2))
        self.assertEqual(r.coverage_score, 0.75)  # golden A3: 9 of 12 months

    def test_error_example(self):
        r = self.report("example_response_error.json")
        self.assertEqual((r.status, r.error.code, r.records), ("error", "E_INVALID_CRITERIA", []))

    def test_meta_example_equals_api(self):
        api = TestClient(create_app(data_dir=ROOT / "data", llm_mode="off")).get("/api/meta").json()
        self.assertEqual(json.loads((EX / "example_meta.json").read_text(encoding="utf-8")), api)


if __name__ == "__main__":
    unittest.main()
