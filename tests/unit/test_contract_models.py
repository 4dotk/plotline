import copy
import json
import unittest

from pydantic import ValidationError

from plotline.contract import (
    ANOMALY_PCT, Criteria, TraceEvent, TrendRecord, TrendReport, canonical_criteria_json,
    report_to_json, window_months,
)
from tests.support import a1_report, a1_report_dict


def invalid(test, fn_or_dict, *needles):
    """Assert the model rejects the input and the message mentions every needle."""
    with test.assertRaises(ValidationError) as cm:
        TrendReport.model_validate(fn_or_dict)
    for n in needles:
        test.assertIn(n, str(cm.exception))


class GoldenReport(unittest.TestCase):
    def test_golden_a1_report_validates(self):
        r = a1_report()
        self.assertEqual(r.coverage_score, 1.0)
        self.assertEqual(len(r.records), 12 * 8)  # 12 months x (ALL + 7 localities)

    def test_report_json_roundtrip_is_stable(self):
        r = a1_report()
        text = report_to_json(r)
        self.assertEqual(report_to_json(TrendReport.model_validate_json(text)), text)

    def test_window_months(self):
        w = window_months("2015-02")
        self.assertEqual((w[0], w[-1], len(w)), ("2014-03", "2015-02", 12))


class ReportRejections(unittest.TestCase):
    def mutate(self, fn):
        d = a1_report_dict()
        fn(d)
        return d

    def test_missing_grid_cell(self):
        invalid(self, self.mutate(lambda d: d["records"].pop()), "dense grid")

    def test_wrong_coverage_score(self):
        invalid(self, self.mutate(lambda d: d.update(coverage_score=0.5)), "coverage_score")

    def test_wrong_n_rows(self):
        invalid(self, self.mutate(lambda d: d["summary"].update(n_rows=1)), "n_rows")

    def test_pct_change_must_match_medians(self):
        def f(d): d["records"][8]["pct_change_price_per_sqft"] = 0.5
        invalid(self, self.mutate(f), "pct_change_price_per_sqft")

    def test_missing_flag(self):
        def f(d): d["anomaly_flags"].pop(); d["diagnostics"].pop()
        invalid(self, self.mutate(f), "anomaly_flags")

    def test_flag_threshold(self):
        def f(d): d["anomaly_flags"][0]["threshold"] = 0.5
        invalid(self, self.mutate(f), "threshold")

    def test_one_diagnostic_per_flag(self):
        invalid(self, self.mutate(lambda d: d["diagnostics"].pop()), "diagnostics")

    def test_direction_matches_change(self):
        def f(d): d["summary"]["price"]["direction"] = "up"
        invalid(self, self.mutate(f), "direction")

    def test_low_sample_rule(self):
        def f(d): d["records"][0]["low_sample"] = True
        invalid(self, self.mutate(f), "low_sample")

    def test_medians_null_iff_empty(self):
        def f(d): d["records"][1]["median_price"] = 1.0
        invalid(self, self.mutate(f), "medians are null")

    def test_pct_change_only_on_all(self):
        def f(d): d["records"][1]["pct_change_price_per_sqft"] = 0.1
        invalid(self, self.mutate(f), "ALL records only")

    def test_price_unit_copy(self):
        invalid(self, self.mutate(lambda d: d.update(price_unit="lakh")), "price_unit")

    def test_unknown_field_rejected(self):
        invalid(self, self.mutate(lambda d: d.update(extra=1)), "extra")

    def test_old_metadata_name_rejected(self):
        def f(d):
            d["metadata"]["application_logic_version"] = d["metadata"].pop("logic_version")
        invalid(self, self.mutate(f), "logic_version")

    def test_loop_counters_must_match_trace(self):
        def f(d): d["metadata"]["loop_counters"]["L2_attempts"] = 1
        invalid(self, self.mutate(f), "loop_counters")

    def test_trace_index_gap(self):
        def f(d): d["trace"][0]["i"] = 1
        invalid(self, self.mutate(f), "trace[0].i")

    def test_ok_report_needs_valid_effective_criteria(self):
        def f(d): d["effective_criteria"]["price_band"] = [9, 1]
        invalid(self, self.mutate(f), "band_inverted")


class ErrorReports(unittest.TestCase):
    def base(self):
        d = a1_report_dict()
        d.update(status="error", error=dict(code="E_LLM_OFF", message="x"), records=[],
                 summary=None, coverage_score=0, anomaly_flags=[], diagnostics=[])
        return d

    def test_valid_error_report(self):
        TrendReport.model_validate(self.base())

    def test_error_with_records_rejected(self):
        d = self.base(); d["records"] = a1_report_dict()["records"][:1]
        invalid(self, d, "records=[]")

    def test_error_needs_code(self):
        d = self.base(); d["error"] = None
        invalid(self, d, "error object")

    def test_unknown_error_code(self):
        d = self.base(); d["error"]["code"] = "E_OTHER"
        invalid(self, d, "E_OTHER")

    def test_error_needs_trace(self):
        d = self.base(); d["trace"] = []
        invalid(self, d, "trace")

    def test_error_may_have_no_criteria_or_topology(self):
        d = self.base()
        d.update(criteria_in=None, effective_criteria=None)
        d["metadata"].update(topology=None, n_scanners=None)
        TrendReport.model_validate(d)


def l1(**over):
    ev = dict(i=0, agent="planner", kind="loop", loop="L1",
              msg='L1 fired: band_inverted; [9,1] -> [1,9]; repair 1 of 2',
              data=dict(issue="band_inverted", before=[9, 1], after=[1, 9], repair_no=1, cap=2))
    ev.update(over); return ev


def l2(attempt=1, **over):
    factor = (0.2, 0.5, "drop")[attempt - 1]
    action = "drop soft filters" if factor == "drop" else f"widen soft ranges by {round(factor * 100)}%"
    ev = dict(i=0, agent="validator", kind="loop", loop="L2",
              msg=f"L2 fired: coverage 3/12 below 9/12; {action}; attempt {attempt} of 3",
              data=dict(coverage_months=3, need_months=9, action=action, factor=factor, attempt=attempt,
                        cap=3, effective_price_band=[6600000, 9400000], decided_by="rule"))
    ev.update(over); return ev


class TraceEvents(unittest.TestCase):
    def test_valid_loop_events(self):
        for ev in (l1(), l2(1), l2(2), l2(3, data=dict(l2(3)["data"], effective_price_band=None))):
            TraceEvent.model_validate(ev)

    def test_l1_msg_template(self):
        with self.assertRaises(ValidationError): TraceEvent.model_validate(l1(msg="L1 fired somehow"))

    def test_l1_repair_number_must_match(self):
        with self.assertRaises(ValidationError):
            TraceEvent.model_validate(l1(data=dict(l1()["data"], repair_no=2)))

    def test_l1_cap_key(self):
        with self.assertRaises(ValidationError):
            TraceEvent.model_validate(l1(data=dict(l1()["data"], cap=5)))

    def test_l1_data_keys(self):
        d = dict(l1()["data"]); d.pop("before")
        with self.assertRaises(ValidationError): TraceEvent.model_validate(l1(data=d))

    def test_l2_requires_decided_by(self):
        d = dict(l2()["data"]); d.pop("decided_by")
        with self.assertRaises(ValidationError): TraceEvent.model_validate(l2(data=d))

    def test_l2_decided_by_values(self):
        with self.assertRaises(ValidationError):
            TraceEvent.model_validate(l2(data=dict(l2()["data"], decided_by="human")))

    def test_l2_factor_follows_attempt(self):
        with self.assertRaises(ValidationError):
            TraceEvent.model_validate(l2(1, data=dict(l2(1)["data"], factor=0.5)))

    def test_l2_fires_only_below_need(self):
        ev = l2(msg="L2 fired: coverage 9/12 below 9/12; widen soft ranges by 20%; attempt 1 of 3",
                data=dict(l2()["data"], coverage_months=9))
        with self.assertRaises(ValidationError): TraceEvent.model_validate(ev)

    def test_attempt_beyond_cap(self):
        with self.assertRaises(ValidationError):
            TraceEvent.model_validate(l2(msg="L2 fired: coverage 3/12 below 9/12; x; attempt 4 of 3"))

    def test_loop_kind_needs_loop_name(self):
        with self.assertRaises(ValidationError): TraceEvent.model_validate(l1(loop=None))

    def test_bad_enum_values(self):
        base = dict(i=0, agent="planner", kind="step", loop=None, msg="", data={})
        for bad in (dict(agent="engine"), dict(kind="info"), dict(i=-1), dict(loop="L3")):
            with self.assertRaises(ValidationError, msg=str(bad)):
                TraceEvent.model_validate({**base, **bad})


class CriteriaShape(unittest.TestCase):
    def test_accepts_requests_that_l1_repairs(self):
        Criteria(localities=["Adyr"], window_end="1999-01", bhk=[9], price_band=[9, 1])

    def test_rejects_bad_shapes(self):
        for kw in (dict(window_end="2015-13"), dict(price_band=[1]), dict(price_band=[1, 2, 3]),
                   dict(price_unit="usd"), dict(bhk=[True]), dict(bhk=["1"]), dict(extra=1)):
            with self.assertRaises(ValidationError, msg=str(kw)):
                Criteria(**kw)

    def test_domain_violations(self):
        c = Criteria(localities=["Adyr"], bhk=[9], price_band=[9, 1])
        self.assertEqual(sorted(c.domain_violations()), ["band_inverted", "bhk_out_of_range", "locality_unknown"])
        self.assertEqual(Criteria().domain_violations(), [])

    def test_canonical_json_sets_and_numbers(self):
        a = Criteria(localities=["T Nagar", "Adyar", "Adyar"], price_band=[7000000, 9000000.5])
        b = Criteria(localities=["Adyar", "T Nagar"], price_band=[7000000, 9000000.5])
        self.assertEqual(canonical_criteria_json(a), canonical_criteria_json(b))
        self.assertIn('"price_band":[7000000,9000000.5]', canonical_criteria_json(a))
        self.assertEqual(canonical_criteria_json(Criteria(price_band=[1, 2])),
                         canonical_criteria_json(Criteria(price_band=[1, 2])))
        self.assertNotEqual(canonical_criteria_json(Criteria(price_band=[1, 2])),
                            canonical_criteria_json(Criteria(price_band=[2, 1])))  # ranges stay ordered pairs

    def test_record_region(self):
        with self.assertRaises(ValidationError):
            TrendRecord(month="2015-02", region_key="Mylapore", listing_count=0, n_in_bucket=0,
                        median_price=None, median_price_per_sqft=None, low_sample=True,
                        pct_change_price_per_sqft=None)


if __name__ == "__main__":
    unittest.main()
