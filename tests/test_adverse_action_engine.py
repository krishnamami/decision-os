"""Unit tests for the RA-7B Adverse Action engine (ECOA / Reg B §1002.9)."""
import unittest

from core.compliance.adverse_action_engine import AdverseActionEngine

RULES = {"adverse_action_days_max": 30}


class HMDAMappingTests(unittest.TestCase):
    def _codes(self, blocking, rules=RULES):
        return AdverseActionEngine(rules).generate_notice("APP-1", blocking)["hmda_denial_codes"]

    def test_dti_block_is_code_1(self):
        self.assertEqual(self._codes(["dti_calculation"]), [1])

    def test_credit_block_is_code_3(self):
        self.assertEqual(self._codes(["credit_assessment"]), [3])

    def test_ltv_block_is_code_4(self):
        self.assertEqual(self._codes(["ltv_assessment"]), [4])

    def test_fraud_block_is_code_6(self):
        self.assertEqual(self._codes(["fraud_screening"]), [6])

    def test_multiple_sorted_and_deduped(self):
        # fraud(6), credit(3), dti(1) -> sorted distinct
        self.assertEqual(
            self._codes(["fraud_screening", "credit_assessment", "dti_calculation"]),
            [1, 3, 6])

    def test_dti_and_income_dedup_to_single_code_1(self):
        self.assertEqual(self._codes(["dti_calculation", "income_verification"]), [1])

    def test_capped_at_four_reasons(self):
        # dti(1), credit(3), ltv(4), fraud(6), compliance(9) -> 5 codes, cap 4
        codes = self._codes([
            "dti_calculation", "credit_assessment", "ltv_assessment",
            "fraud_screening", "compliance_check"])
        self.assertEqual(len(codes), 4)
        self.assertEqual(codes, [1, 3, 4, 6])


class NoticeShapeTests(unittest.TestCase):
    def test_deadline_from_decision_date(self):
        n = AdverseActionEngine(RULES).generate_notice(
            "APP-1", ["credit_assessment"], decision_date="2026-06-01")
        self.assertEqual(n["decision_date"], "2026-06-01")
        self.assertEqual(n["notice_deadline"], "2026-07-01")  # +30 days
        self.assertEqual(n["days_to_notice"], 30)

    def test_denial_reasons_carry_text_and_decision(self):
        n = AdverseActionEngine(RULES).generate_notice("APP-1", ["credit_assessment"])
        r = n["denial_reasons"][0]
        self.assertEqual(r["hmda_code"], 3)
        self.assertEqual(r["reason"], "Credit history")
        self.assertEqual(r["decision"], "credit_assessment")

    def test_ecoa_and_citation_present(self):
        n = AdverseActionEngine(RULES).generate_notice("APP-1", ["dti_calculation"])
        self.assertIn("Equal Credit Opportunity Act", n["ecoa_rights_statement"])
        self.assertIn("1691", n["citation"])
        self.assertEqual(n["notice_type"], "ADVERSE_ACTION")
        self.assertTrue(n["fcra_disclosure_required"])  # credit_bureau_used default

    def test_no_blocking_decisions_is_empty(self):
        n = AdverseActionEngine(RULES).generate_notice("APP-1", [])
        self.assertEqual(n["hmda_denial_codes"], [])
        self.assertEqual(n["denial_reasons"], [])


class DeadlineSourceTests(unittest.TestCase):
    def test_catalogue_days_used(self):
        e = AdverseActionEngine({"adverse_action_days_max": 15})
        self.assertEqual(e.days_max, 15)

    def test_default_when_no_rule(self):
        self.assertEqual(AdverseActionEngine().days_max, 30)

    def test_none_falls_back_to_default(self):
        self.assertEqual(
            AdverseActionEngine({"adverse_action_days_max": None}).days_max, 30)


if __name__ == "__main__":
    unittest.main()
