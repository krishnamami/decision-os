"""Unit tests for the EX-C ExceptionWorkflowService.can_approve (pure authority
logic) + the de-hardcoded EX-B score->level thresholds. RULE 11: data_source +
missing_inputs on every return. (transition_status / register / writer are DB
integration code, verified by the backfill run + 16/16.)"""
import unittest

from core.exceptions.compensating_factors_engine import CompensatingFactorsEngine
from core.exceptions.exception_workflow import APPROVER_AUTHORITY, ExceptionWorkflowService

W = ExceptionWorkflowService()  # SAFE_DEFAULTS: agency floor absolute


class CanApproveTests(unittest.TestCase):
    def test_below_agency_floor_blocks_any_role(self):
        for role in ("uw", "uw_manager", "senior_credit_officer", "credit_committee"):
            r = W.can_approve(role, "uw_approval", below_agency_floor=True)
            self.assertFalse(r["can_approve"], role)
            self.assertEqual(r["reason"], "below_agency_floor_absolute")
            self.assertEqual(r["missing_inputs"], [])

    def test_uw_cannot_approve_senior(self):
        r = W.can_approve("uw", "senior_uw_approval", below_agency_floor=False)
        self.assertFalse(r["can_approve"])
        self.assertEqual(r["reason"], "insufficient_authority")
        self.assertEqual(r["required_role"], "senior_credit_officer")

    def test_manager_approves_manager_level(self):
        r = W.can_approve("uw_manager", "uw_manager_approval", below_agency_floor=False)
        self.assertTrue(r["can_approve"])
        self.assertIn("data_source", r)

    def test_senior_approves_senior_level(self):
        self.assertTrue(W.can_approve("senior_credit_officer", "senior_uw_approval",
                                      False)["can_approve"])

    def test_committee_approves_senior(self):
        self.assertTrue(W.can_approve("credit_committee", "senior_uw_approval",
                                      False)["can_approve"])

    def test_insufficient_factors_blocked(self):
        r = W.can_approve("senior_credit_officer", "insufficient_factors", False)
        self.assertFalse(r["can_approve"])
        self.assertEqual(r["reason"], "insufficient_factors")

    def test_floor_not_absolute_when_rule_false(self):
        w2 = ExceptionWorkflowService(rules={"exception_cannot_breach_agency_floor": False})
        r = w2.can_approve("senior_credit_officer", "senior_uw_approval",
                           below_agency_floor=True)
        self.assertTrue(r["can_approve"])  # floor no longer absolute (custom rule)

    def test_required_role_map(self):
        self.assertEqual(W._required_role_for("uw_manager_approval"), "uw_manager")
        self.assertEqual(W._required_role_for("senior_uw_approval"), "senior_credit_officer")

    def test_authority_map_shape(self):
        self.assertIn("senior_uw_approval", APPROVER_AUTHORITY["credit_committee"])
        self.assertNotIn("senior_uw_approval", APPROVER_AUTHORITY["uw"])


class ScoreThresholdInjectionTests(unittest.TestCase):
    """RULE 1 fix: the 9/5/2 score->level thresholds are catalogue-driven."""

    def test_default_thresholds(self):
        e = CompensatingFactorsEngine()
        self.assertEqual((e._score_senior_min, e._score_manager_min, e._score_uw_min),
                         (9, 5, 2))

    def test_custom_thresholds_flow_through(self):
        e = CompensatingFactorsEngine(rules={
            "exception_score_senior_min": 15, "exception_score_manager_min": 8,
            "exception_score_uw_min": 3})
        # score 5: default -> manager; custom (manager=8) -> uw (5>=3, <8).
        inputs = {"total_liquid_assets": 24500, "piti_monthly": 1800,
                  "mid_credit_score": 712, "min_credit_score_applied": 660}
        out = e.detect_all(inputs)
        self.assertEqual(out["exception_score"], 5)
        self.assertEqual(out["approval_level"], "uw_approval")
        self.assertEqual(CompensatingFactorsEngine().detect_all(inputs)["approval_level"],
                         "uw_manager_approval")  # default thresholds


if __name__ == "__main__":
    unittest.main()
