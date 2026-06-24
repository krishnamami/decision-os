"""Unit tests for the RA-AUS-C LP (Loan Product Advisor) parser + its
reconciliation through the shared AUSReconciliationEngine."""
import unittest

from core.aus.lp_parser import LPParser
from core.aus.reconciliation import AUSReconciliationEngine

PARSE = LPParser().parse
ENGINE = AUSReconciliationEngine()


class RecommendationTests(unittest.TestCase):
    def test_accept(self):
        r = PARSE({"recommendation": "Accept"})
        self.assertEqual(r["recommendation"], "ACCEPT")
        self.assertTrue(r["accept"])
        self.assertTrue(r["approve"])   # alias for the shared engine
        self.assertTrue(r["eligible"])

    def test_accept_eligible_variant(self):
        r = PARSE({"recommendation": "Accept/Eligible"})
        self.assertEqual(r["recommendation"], "ACCEPT")
        self.assertTrue(r["accept"])

    def test_caution_is_eligible_not_accept(self):
        # LP Caution = elevated risk but STILL eligible (DU Refer/Eligible analogue).
        r = PARSE({"recommendation": "Caution"})
        self.assertEqual(r["recommendation"], "CAUTION")
        self.assertFalse(r["accept"])
        self.assertFalse(r["approve"])
        self.assertTrue(r["eligible"])

    def test_ineligible(self):
        r = PARSE({"recommendation": "Ineligible"})
        self.assertEqual(r["recommendation"], "INELIGIBLE")
        self.assertFalse(r["accept"])
        self.assertFalse(r["eligible"])

    def test_out_of_scope(self):
        r = PARSE({"recommendation": "Out of Scope"})
        self.assertEqual(r["recommendation"], "OUT_OF_SCOPE")
        self.assertFalse(r["accept"])
        self.assertFalse(r["eligible"])

    def test_risk_grade_shorthand_maps(self):
        self.assertEqual(PARSE({"recommendation": "A+"})["recommendation"], "ACCEPT")
        self.assertEqual(PARSE({"recommendation": "B"})["recommendation"], "CAUTION")
        self.assertEqual(PARSE({"recommendation": "D"})["recommendation"], "INELIGIBLE")

    def test_unknown_recommendation_passes_through(self):
        r = PARSE({"recommendation": "Brand New"})
        self.assertEqual(r["recommendation"], "Brand New")
        self.assertFalse(r["accept"])


class RiskClassTests(unittest.TestCase):
    def test_risk_classes_mapped(self):
        self.assertEqual(PARSE({"risk_class": "A+"})["risk_class"], "exceptional")
        self.assertEqual(PARSE({"risk_class": "A"})["risk_class"], "acceptable")
        self.assertEqual(PARSE({"risk_class": "B"})["risk_class"], "elevated")
        self.assertEqual(PARSE({"risk_class": "C"})["risk_class"], "high_risk")
        self.assertEqual(PARSE({"risk_class": "D"})["risk_class"], "very_high_risk")
        self.assertEqual(PARSE({"risk_class": "E"})["risk_class"], "not_eligible")


class FeedbacksConditionsTests(unittest.TestCase):
    def test_feedbacks_dict_and_string(self):
        r = PARSE({"feedbacks": [
            {"id": "FB1", "type": "asset", "description": "reserves low",
             "severity": "warning", "category": "assets"},
            "Verify rental income",
        ]})
        self.assertEqual(r["feedback_count"], 2)
        self.assertEqual(r["feedbacks"][0]["feedback_id"], "FB1")
        self.assertEqual(r["feedbacks"][0]["severity"], "warning")
        self.assertEqual(r["feedbacks"][1]["feedback_type"], "message")

    def test_conditions_dict_and_string(self):
        r = PARSE({"conditions": [
            {"id": "C1", "type": "prior_to_close", "description": "flood cert"},
            "Provide HOI",
        ]})
        self.assertEqual(r["condition_count"], 2)
        self.assertEqual(r["conditions"][0]["condition_id"], "C1")
        self.assertEqual(r["conditions"][1]["condition_type"], "prior_to_purchase")

    def test_full_shape(self):
        r = PARSE({"recommendation": "Accept", "version": "5.0",
                   "key_number": "LP999", "risk_class": "A+"})
        self.assertEqual(r["system"], "LP")
        self.assertEqual(r["key_number"], "LP999")
        self.assertIn("Freddie Mac LP", r["citation"])


class LPReconciliationTests(unittest.TestCase):
    """LP results flow through the SAME engine as DU (approve/eligible alias)."""

    def test_lp_accept_vs_accord_block_high_conflict(self):
        r = ENGINE.reconcile("block", PARSE({"recommendation": "Accept"}))
        self.assertTrue(r["reconciliation_required"])
        self.assertEqual(r["conflict"], "ACCORD_BLOCK_DU_APPROVE")
        self.assertEqual(r["risk"], "HIGH")

    def test_lp_caution_vs_accord_block_agree(self):
        # Both cautious / negative -> agreement, not a conflict.
        r = ENGINE.reconcile("block", PARSE({"recommendation": "Caution"}))
        self.assertFalse(r["reconciliation_required"])
        self.assertTrue(r["agreement"])

    def test_lp_accept_vs_accord_recommend_agree(self):
        r = ENGINE.reconcile("recommend", PARSE({"recommendation": "Accept"}))
        self.assertFalse(r["reconciliation_required"])
        self.assertTrue(r["agreement"])
        self.assertEqual(r["confidence"], "HIGH")

    def test_lp_ineligible_vs_accord_recommend_high_conflict(self):
        r = ENGINE.reconcile("recommend", PARSE({"recommendation": "Ineligible"}))
        self.assertEqual(r["conflict"], "ACCORD_RECOMMEND_DU_REFER")
        self.assertEqual(r["risk"], "HIGH")


if __name__ == "__main__":
    unittest.main()
