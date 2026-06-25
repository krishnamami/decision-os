"""Unit tests for the EX-A ExceptionEngine. Thresholds proven to come from the
rules dict (catalogue), SAFE_DEFAULTS fallback. RULE 11: every return carries
data_source + missing_inputs."""
import unittest

from core.exceptions.exception_engine import (
    EXCEPTION_RULE_KEYS,
    ExceptionEngine,
)

E = ExceptionEngine()  # no rules -> SAFE_DEFAULTS (requires factors, 5% breach, floor absolute)


class AgencyFloorTests(unittest.TestCase):
    def test_below_agency_floor_not_eligible(self):
        r = E.evaluate_exception_eligibility(
            blocked_signal="CREDIT_FAILS", actual_value=580,
            overlay_threshold=620, agency_floor=600, compensating_factors=[])
        self.assertFalse(r["eligible_for_exception"])
        self.assertEqual(r["reason"], "below_agency_floor")
        self.assertEqual(r["missing_inputs"], [])
        self.assertIn("agency_guidelines", r["data_source"])

    def test_floor_breach_allowed_when_rule_false(self):
        e2 = ExceptionEngine(rules={"exception_cannot_breach_agency_floor": False})
        r = e2.evaluate_exception_eligibility(
            blocked_signal="CREDIT_FAILS", actual_value=580,
            overlay_threshold=None, agency_floor=600, compensating_factors=["x"])
        self.assertTrue(r["eligible_for_exception"])  # floor no longer absolute


class BreachToleranceTests(unittest.TestCase):
    def test_breach_exceeds_max_not_eligible(self):
        r = E.evaluate_exception_eligibility(
            blocked_signal="DTI_EXCEEDS", actual_value=48, overlay_threshold=43,
            agency_floor=None, compensating_factors=[])
        self.assertFalse(r["eligible_for_exception"])  # ~11.6% > 5%
        self.assertEqual(r["reason"], "breach_exceeds_maximum")

    def test_within_breach_eligible_factors_required(self):
        r = E.evaluate_exception_eligibility(
            blocked_signal="DTI_EXCEEDS", actual_value=45, overlay_threshold=43,
            agency_floor=None, compensating_factors=[])
        self.assertTrue(r["eligible_for_exception"])     # ~4.65% <= 5%
        self.assertEqual(r["reason"], "compensating_factors_required")
        self.assertTrue(r["docs_needed"])
        self.assertTrue(r["missing_inputs"])             # factors absent

    def test_eligible_with_factors_clean(self):
        r = E.evaluate_exception_eligibility(
            blocked_signal="DTI_EXCEEDS", actual_value=45, overlay_threshold=43,
            agency_floor=None, compensating_factors=["substantial_reserves"])
        self.assertTrue(r["eligible_for_exception"])
        self.assertEqual(r["reason"], "eligible_with_factors")
        self.assertEqual(r["compensating_factors_count"], 1)
        self.assertEqual(r["missing_inputs"], [])        # all inputs present

    def test_custom_breach_tolerance_flows_through(self):
        # 9.3% breach: rejected at default 5%, allowed at custom 10%.
        kw = dict(blocked_signal="DTI_EXCEEDS", actual_value=47,
                  overlay_threshold=43, agency_floor=None,
                  compensating_factors=["low_ltv"])
        self.assertFalse(E.evaluate_exception_eligibility(**kw)["eligible_for_exception"])
        e10 = ExceptionEngine(rules={"exception_max_dti_overlay_breach_pct": 10})
        out = e10.evaluate_exception_eligibility(**kw)
        self.assertTrue(out["eligible_for_exception"])
        self.assertAlmostEqual(out["breach_pct"], 9.3, places=1)


class ClassifyTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(E.classify_exception_type("DTI_EXCEEDS_LIMIT"), "dti_overlay_breach")
        self.assertEqual(E.classify_exception_type("LTV_EXCEEDS_LIMIT"), "ltv_overlay_breach")
        self.assertEqual(E.classify_exception_type("CREDIT_FAILS_OVERLAY"), "credit_overlay_breach")
        self.assertEqual(E.classify_exception_type("AUS_CONFLICT"), "aus_conflict")
        self.assertEqual(E.classify_exception_type("ROUTE_CONFLICT_PRESENT"), "manual_underwrite")
        self.assertEqual(E.classify_exception_type("SOMETHING_ELSE"), "other")


class MetaTests(unittest.TestCase):
    def test_rule_keys(self):
        # The 4 core exception keys must be present; EX-B extended the list with
        # the compensating-factor thresholds (one shared exception_rules bundle key).
        for k in ("exception_requires_compensating_factors",
                  "exception_max_dti_overlay_breach_pct",
                  "exception_max_ltv_overlay_breach_pct",
                  "exception_cannot_breach_agency_floor"):
            self.assertIn(k, EXCEPTION_RULE_KEYS)

    def test_every_return_has_rule_11_keys(self):
        # RULE 11: data_source + missing_inputs on every path.
        for kw in (
            dict(blocked_signal="CREDIT_FAILS", actual_value=580, overlay_threshold=620,
                 agency_floor=600, compensating_factors=[]),                    # floor
            dict(blocked_signal="DTI_EXCEEDS", actual_value=48, overlay_threshold=43,
                 agency_floor=None, compensating_factors=[]),                   # breach
            dict(blocked_signal="DTI_EXCEEDS", actual_value=45, overlay_threshold=43,
                 agency_floor=None, compensating_factors=[]),                   # factors-required
            dict(blocked_signal="DTI_EXCEEDS", actual_value=45, overlay_threshold=43,
                 agency_floor=None, compensating_factors=["x"]),               # clean
        ):
            r = E.evaluate_exception_eligibility(**kw)
            self.assertIn("data_source", r)
            self.assertIn("missing_inputs", r)


if __name__ == "__main__":
    unittest.main()
