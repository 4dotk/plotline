"""T21: FastAPI app, goal 'UI-shaped JSON returned from real engine'.

Uses the real frozen snapshot and the engine as it currently is (stub agents
until T17-T20 land). Assertions are on shape and contract rules, not on stub
values, so they keep holding when the real agents replace the stubs.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from plotline.api import create_app
from plotline.contract import CANONICAL_LOCALITIES, TrendReport

DATA = Path(__file__).resolve().parent.parent / "data"
SHA = (DATA / "SNAPSHOT.sha256").read_text().split()[0]
META_KEYS = {
    "localities", "bhk_values", "sale_conds", "first_month", "latest_month", "window_end_min",
    "window_end_max", "default_window_end", "sales_per_month", "localities_active_by_month",
    "snapshot_sha256", "constants", "partial_months",
}


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(create_app(data_dir=DATA, llm_mode="off"))

    def post(self, body):
        return self.client.post("/api/run", json=body)

    # -- health ---------------------------------------------------------------

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(set(j), {"status", "llm_mode", "snapshot_sha256", "logic_version", "contract_version"})
        self.assertEqual(j["status"], "ok")
        self.assertEqual(j["llm_mode"], "off")
        self.assertEqual(j["snapshot_sha256"], SHA)

    # -- meta -----------------------------------------------------------------

    def test_meta_keys_and_values(self):
        j = self.client.get("/api/meta").json()
        self.assertEqual(set(j), META_KEYS)
        self.assertEqual(j["localities"], list(CANONICAL_LOCALITIES))
        self.assertEqual(j["bhk_values"], [1, 2, 3, 4])
        self.assertEqual(j["first_month"], "2004-01")
        self.assertEqual(j["latest_month"], "2015-02")
        self.assertEqual(j["window_end_min"], "2004-12")
        self.assertEqual(j["window_end_max"], "2015-02")
        self.assertEqual(j["default_window_end"], "2015-02")
        self.assertEqual(j["partial_months"], ["2004-01", "2015-02"])
        self.assertEqual(j["snapshot_sha256"], SHA)

    def test_meta_sales_per_month(self):
        j = self.client.get("/api/meta").json()
        spm = j["sales_per_month"]
        self.assertEqual(spm[0]["month"], "2004-01")
        self.assertEqual(spm[-1]["month"], "2015-02")
        self.assertEqual(len(spm), 134)  # 2004-01 .. 2015-02, no gaps
        self.assertEqual(sum(x["count"] for x in spm), 7108)  # every snapshot row
        months = [x["month"] for x in spm]
        self.assertEqual(months, sorted(months))
        window_ends = [m for m in months if j["window_end_min"] <= m <= j["window_end_max"]]
        self.assertEqual(len(window_ends), 123)  # contract 4.4

    def test_meta_active_localities(self):
        j = self.client.get("/api/meta").json()
        act = j["localities_active_by_month"]
        self.assertEqual([a["month"] for a in act], [x["month"] for x in j["sales_per_month"]])
        for a, s in zip(act, j["sales_per_month"]):
            self.assertEqual(bool(a["localities"]), s["count"] > 0)
            self.assertTrue(set(a["localities"]) <= set(CANONICAL_LOCALITIES))

    # -- run ------------------------------------------------------------------

    def test_run_default_returns_valid_report(self):
        r = self.post({"criteria": {}})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("application/json"))
        rep = TrendReport.model_validate_json(r.content)  # contract-valid, UI-shaped
        self.assertEqual(rep.status, "ok")
        self.assertEqual(rep.effective_criteria.window_end, "2015-02")
        self.assertEqual(len(rep.records), 12 * (len(CANONICAL_LOCALITIES) + 1))  # dense grid
        self.assertEqual(rep.metadata.snapshot_sha256, SHA)
        self.assertEqual([e.i for e in rep.trace], list(range(len(rep.trace))))

    def test_run_with_filters(self):
        r = self.post({"criteria": {"localities": ["Adyar", "T Nagar"], "bhk": [2], "window_end": "2014-06"},
                       "seed": 5, "options": {"force_topology": "consolidated"}})
        self.assertEqual(r.status_code, 200)
        rep = TrendReport.model_validate_json(r.content)
        self.assertEqual(rep.metadata.seed, 5)
        self.assertEqual(rep.metadata.topology, "consolidated")
        self.assertEqual(rep.effective_criteria.window_end, "2014-06")

    def test_run_identical_bytes(self):  # I-DET through the API
        body = {"criteria": {"localities": ["Adyar"]}, "seed": 3}
        self.assertEqual(self.post(body).content, self.post(body).content)

    def test_domain_error_is_http_200(self):  # I-ERR
        r = self.post({"nl_query": "flats in Adyar last year"})  # llm_mode off
        self.assertEqual(r.status_code, 200)
        rep = TrendReport.model_validate_json(r.content)
        self.assertEqual(rep.status, "error")
        self.assertEqual(rep.error.code, "E_LLM_OFF")
        self.assertEqual(rep.records, [])

    def test_invalid_criteria_still_http_200_and_valid(self):
        r = self.post({"criteria": {"localities": ["Xyz"]}})
        self.assertEqual(r.status_code, 200)
        TrendReport.model_validate_json(r.content)  # ok or error, but always a valid report

    def test_malformed_body_is_422(self):
        self.assertEqual(self.post({}).status_code, 422)  # neither criteria nor nl_query
        self.assertEqual(self.post({"criteria": {}, "nl_query": "x"}).status_code, 422)  # both
        self.assertEqual(self.post({"criteria": {"bogus": 1}}).status_code, 422)  # unknown field
        self.assertEqual(self.post({"criteria": {"bhk": "two"}}).status_code, 422)  # wrong type

    # -- CORS -----------------------------------------------------------------

    def test_cors_preflight_and_headers(self):
        h = {"Origin": "https://example.lovable.app", "Access-Control-Request-Method": "POST",
             "Access-Control-Request-Headers": "content-type"}
        r = self.client.options("/api/run", headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertIn(r.headers["access-control-allow-origin"], ("*", "https://example.lovable.app"))
        r = self.client.get("/api/meta", headers={"Origin": "https://example.lovable.app"})
        self.assertIn("access-control-allow-origin", r.headers)


class SnapshotMismatch(unittest.TestCase):
    def test_bad_hash_gives_error_report_not_crash(self):
        import shutil, tempfile

        with tempfile.TemporaryDirectory() as t:
            for n in ("chennai_snapshot.csv", "SNAPSHOT.sha256"):
                shutil.copy(DATA / n, t)
            (Path(t) / "SNAPSHOT.sha256").write_text("0" * 64 + "  chennai_snapshot.csv\n")
            c = TestClient(create_app(data_dir=t, llm_mode="off"))
            self.assertEqual(c.get("/api/health").status_code, 200)
            r = c.post("/api/run", json={"criteria": {}})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(json.loads(r.content)["error"]["code"], "E_SNAPSHOT_HASH")


if __name__ == "__main__":
    unittest.main()
