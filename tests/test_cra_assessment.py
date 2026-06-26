"""Unit tests for CF-C CRA assessment (pure, no DB).

Covers the tier classifier (federal AMI cutoffs), the applicability gate, the honest
insufficient_data path (meridian reality), and the computed assessment + internal
benchmark rating. RULE 11 + the non-regulatory disclaimer asserted throughout.
Income is full dollars (matches hmda_lar.applicant_income).
"""
import unittest

from core.compliance.cra_assessment import CRAAssessment, classify_income_tier

CUTOFFS = {"low_max": 50, "moderate_max": 80, "middle_max": 120}


class TierClassifierTests(unittest.TestCase):
    def test_low(self):
        self.assertEqual(classify_income_tier(45000, 100000, CUTOFFS), "low")

    def test_moderate(self):
        self.assertEqual(classify_income_tier(65000, 100000, CUTOFFS), "moderate")

    def test_middle(self):
        self.assertEqual(classify_income_tier(95000, 100000, CUTOFFS), "middle")

    def test_upper(self):
        self.assertEqual(classify_income_tier(130000, 100000, CUTOFFS), "upper")

    def test_boundary_50_is_moderate(self):
        # exactly 50% AMI -> not < 50 -> moderate (low is strictly < 50%)
        self.assertEqual(classify_income_tier(50000, 100000, CUTOFFS), "moderate")

    def test_none_inputs(self):
        self.assertIsNone(classify_income_tier(None, 100000, CUTOFFS))
        self.assertIsNone(classify_income_tier(50000, None, CUTOFFS))

    def test_zero_ami(self):
        self.assertIsNone(classify_income_tier(50000, 0, CUTOFFS))


class ApplicabilityTests(unittest.TestCase):
    def setUp(self):
        self.a = CRAAssessment()

    def test_imc_not_applicable(self):
        out = self.a.assess([], institution_type="imc", tenant_id="t")
        self.assertEqual(out["status"], "not_applicable")
        self.assertIn("does not apply", out["reason"])

    def test_broker_not_applicable(self):
        self.assertEqual(self.a.assess([], institution_type="broker")["status"], "not_applicable")

    def test_bank_proceeds(self):
        out = self.a.assess([], institution_type="bank")
        self.assertNotEqual(out["status"], "not_applicable")

    def test_credit_union_proceeds(self):
        out = self.a.assess([], institution_type="credit_union")
        self.assertNotEqual(out["status"], "not_applicable")

    def test_unset_type_proceeds_to_data_check(self):
        # meridian company_type unset -> not gated out; falls to data check
        out = self.a.assess([], institution_type="")
        self.assertEqual(out["status"], "insufficient_data")


class InsufficientDataTests(unittest.TestCase):
    def setUp(self):
        self.a = CRAAssessment()

    def test_null_tracts(self):
        loans = [{"census_tract": None, "action_taken": "1", "loan_amount": 400000}] * 16
        out = self.a.assess(loans, institution_type="bank", tenant_id="meridian")
        self.assertEqual(out["status"], "insufficient_data")
        self.assertTrue(any("census_tract" in g for g in out["collection_gaps"]))
        self.assertEqual(out["missing_inputs"], out["collection_gaps"])

    def test_no_ami(self):
        loans = [{"census_tract": "11001", "action_taken": "1"}]
        out = self.a.assess(loans, area_median_income=None,
                            tract_incomes={"11001": 45000}, institution_type="bank")
        self.assertEqual(out["status"], "insufficient_data")
        self.assertTrue(any("area_median_income" in g for g in out["collection_gaps"]))

    def test_no_tract_incomes(self):
        loans = [{"census_tract": "11001", "action_taken": "1"}]
        out = self.a.assess(loans, area_median_income=100000, tract_incomes=None,
                            institution_type="bank")
        self.assertEqual(out["status"], "insufficient_data")


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.a = CRAAssessment()
        self.loans = [
            {"census_tract": "11001", "action_taken": "1", "loan_amount": 300000, "income": 40000},
            {"census_tract": "11002", "action_taken": "1", "loan_amount": 400000, "income": 90000},
            {"census_tract": "11003", "action_taken": "3", "loan_amount": 300000, "income": 35000},
        ]
        self.tracts = {"11001": 45000, "11002": 95000, "11003": 42000}  # low, middle, low

    def test_assessed_status(self):
        out = self.a.assess(self.loans, area_median_income=100000, tract_incomes=self.tracts,
                            institution_type="bank", period="2024")
        self.assertEqual(out["status"], "assessed")
        self.assertEqual(out["originated_loans"], 2)  # action 3 (denied) excluded

    def test_lmi_tract_ratio(self):
        out = self.a.assess(self.loans, area_median_income=100000, tract_incomes=self.tracts,
                            institution_type="bank")
        # originated: 11001(low) + 11002(middle) -> 1 of 2 in LMI = 50%
        self.assertEqual(out["metrics"]["lmi_tract_ratio_pct"], 50.0)
        self.assertEqual(out["metrics"]["lmi_tract_loans"], 1)

    def test_lmi_borrower_ratio(self):
        out = self.a.assess(self.loans, area_median_income=100000, tract_incomes=self.tracts,
                            institution_type="bank")
        # originated incomes 40000 (<80k LMI) + 90000 (not) -> 1 of 2 = 50%
        self.assertEqual(out["metrics"]["lmi_borrower_ratio_pct"], 50.0)

    def test_internal_rating_outstanding(self):
        out = self.a.assess(self.loans, area_median_income=100000, tract_incomes=self.tracts,
                            institution_type="bank")
        # 50% LMI ratio >= 40 -> outstanding
        self.assertEqual(out["internal_benchmark"]["rating"], "outstanding")

    def test_rating_thresholds(self):
        self.assertEqual(self.a._internal_rating(45), "outstanding")
        self.assertEqual(self.a._internal_rating(30), "satisfactory")
        self.assertEqual(self.a._internal_rating(15), "needs_to_improve")
        self.assertEqual(self.a._internal_rating(5), "substantial_noncompliance")

    def test_disclaimer_present(self):
        out = self.a.assess(self.loans, area_median_income=100000, tract_incomes=self.tracts,
                            institution_type="bank")
        self.assertIn("internal self-assessment", out["internal_benchmark"]["disclaimer"].lower())
        self.assertIn("examiners", out["internal_benchmark"]["disclaimer"].lower())

    def test_custom_cutoffs_flow_from_rules(self):
        # RULE 1: cutoffs from injected rules, not hardcoded
        a = CRAAssessment(rules={"cra_lmi_low_max_pct": 60})
        self.assertEqual(a._cutoffs["low_max"], 60.0)
        # 55% AMI now classifies as 'low' (< 60)
        self.assertEqual(classify_income_tier(55000, 100000, a._cutoffs), "low")

    def test_rule11_provenance(self):
        out = self.a.assess(self.loans, area_median_income=100000, tract_incomes=self.tracts,
                            institution_type="bank")
        self.assertIn("data_source", out)
        self.assertIn("missing_inputs", out)
        self.assertIn("citation", out)


if __name__ == "__main__":
    unittest.main()
