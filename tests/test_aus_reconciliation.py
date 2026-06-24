"""Unit tests for the RA-AUS-B reconciliation engine."""
import unittest

from core.aus.du_parser import DUParser
from core.aus.reconciliation import AUSReconciliationEngine

PARSE = DUParser().parse
ENGINE = AUSReconciliationEngine()


def _du(rec):
    return PARSE({"recommendation": rec})


class ConflictCaseTests(unittest.TestCase):
    def test_case1_block_vs_approve_high(self):
        r = ENGINE.reconcile("block", _du("Approve/Eligible"))
        self.assertTrue(r["reconciliation_required"])
        self.assertEqual(r["conflict"], "ACCORD_BLOCK_DU_APPROVE")
        self.assertEqual(r["risk"], "HIGH")
        self.assertEqual(r["confidence"], "LOW")
        self.assertTrue(r["uw_action"])
        self.assertTrue(r["hmda_implication"])

    def test_case2_recommend_vs_refer_ineligible_high(self):
        r = ENGINE.reconcile("recommend", _du("Refer/Ineligible"))
        self.assertEqual(r["conflict"], "ACCORD_RECOMMEND_DU_REFER")
        self.assertEqual(r["risk"], "HIGH")

    def test_case3_escalate_vs_approve_medium(self):
        r = ENGINE.reconcile("escalate", _du("Approve/Eligible"))
        self.assertEqual(r["conflict"], "ACCORD_ESCALATE_DU_APPROVE")
        self.assertEqual(r["risk"], "MEDIUM")
        self.assertEqual(r["confidence"], "MEDIUM")

    def test_case4_recommend_vs_refer_eligible_low(self):
        r = ENGINE.reconcile("recommend", _du("Refer/Eligible"))
        self.assertEqual(r["conflict"], "ACCORD_RECOMMEND_DU_REFER_ELIGIBLE")
        self.assertEqual(r["risk"], "LOW")
        self.assertEqual(r["confidence"], "MEDIUM")


class AgreementTests(unittest.TestCase):
    def test_block_and_refer_agree(self):
        # both say no -> agreement, not a conflict
        r = ENGINE.reconcile("block", _du("Refer/Ineligible"))
        self.assertFalse(r["reconciliation_required"])
        self.assertTrue(r["agreement"])
        self.assertEqual(r["confidence"], "HIGH")

    def test_recommend_and_approve_agree(self):
        r = ENGINE.reconcile("recommend", _du("Approve/Eligible"))
        self.assertFalse(r["reconciliation_required"])
        self.assertTrue(r["agreement"])

    def test_allow_and_approve_agree(self):
        r = ENGINE.reconcile("allow", _du("Approve/Eligible"))
        self.assertFalse(r["reconciliation_required"])

    def test_no_aus_response(self):
        r = ENGINE.reconcile("block", None)
        self.assertFalse(r["reconciliation_required"])
        self.assertIsNone(r["conflict"])
        self.assertIn("No AUS", r["message"])


class MappingTests(unittest.TestCase):
    def test_conflict_strings_from_map_not_inline(self):
        from core.aus.reconciliation import CONFLICT_EXPLANATIONS
        for key in ("ACCORD_BLOCK_DU_APPROVE", "ACCORD_RECOMMEND_DU_REFER",
                    "ACCORD_ESCALATE_DU_APPROVE",
                    "ACCORD_RECOMMEND_DU_REFER_ELIGIBLE"):
            self.assertIn(key, CONFLICT_EXPLANATIONS)
            self.assertIn(CONFLICT_EXPLANATIONS[key]["risk"], ("HIGH", "MEDIUM", "LOW"))


if __name__ == "__main__":
    unittest.main()
