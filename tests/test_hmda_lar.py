"""Unit tests for the RA-7C HMDA LAR generator (Reg C, 12 CFR Part 1003)."""
import unittest

from core.compliance.hmda_lar import HMDALARGenerator

GEN = HMDALARGenerator()

LOAN_FIELDS = {
    "loan_amount": 400000, "interest_rate": 6.5, "loan_type": "Conventional",
    "loan_purpose": "Purchase", "qualifying_monthly": 10000,
}


class ActionTakenTests(unittest.TestCase):
    def test_recommend_is_originated(self):
        r = GEN.generate_lar_record("APP-1", LOAN_FIELDS, outcome="recommend")
        self.assertEqual(r["action_taken"], 1)

    def test_allow_is_originated(self):
        self.assertEqual(
            GEN.generate_lar_record("APP-1", LOAN_FIELDS, outcome="allow")["action_taken"], 1)

    def test_escalate_is_approved_not_accepted(self):
        self.assertEqual(
            GEN.generate_lar_record("APP-1", LOAN_FIELDS, outcome="escalate")["action_taken"], 2)

    def test_block_is_denied(self):
        self.assertEqual(
            GEN.generate_lar_record("APP-1", LOAN_FIELDS, outcome="block")["action_taken"], 3)

    def test_unknown_outcome_is_incomplete(self):
        self.assertEqual(
            GEN.generate_lar_record("APP-1", LOAN_FIELDS, outcome="???")["action_taken"], 5)


class DenialReasonTests(unittest.TestCase):
    def test_block_with_adverse_action_carries_codes(self):
        aa = {"hmda_denial_codes": [1, 3, 4]}
        r = GEN.generate_lar_record("APP-1", LOAN_FIELDS, outcome="block", adverse_action=aa)
        self.assertEqual(r["denial_reasons"], [1, 3, 4])

    def test_denial_reasons_capped_at_four(self):
        aa = {"hmda_denial_codes": [1, 2, 3, 4, 6]}
        r = GEN.generate_lar_record("APP-1", LOAN_FIELDS, outcome="block", adverse_action=aa)
        self.assertEqual(len(r["denial_reasons"]), 4)

    def test_no_denial_reasons_when_originated(self):
        aa = {"hmda_denial_codes": [1]}
        r = GEN.generate_lar_record("APP-1", LOAN_FIELDS, outcome="recommend", adverse_action=aa)
        self.assertEqual(r["denial_reasons"], [])


class DemographicTests(unittest.TestCase):
    def test_defaults_to_not_provided(self):
        r = GEN.generate_lar_record("APP-1", LOAN_FIELDS, outcome="recommend")
        self.assertEqual(r["applicant_ethnicity"], 3)  # FFIEC not-provided
        self.assertEqual(r["applicant_race"], 6)
        self.assertEqual(r["applicant_sex"], 3)
        self.assertFalse(r["demographic_data_provided"])

    def test_demographic_mapped_when_present(self):
        f = dict(LOAN_FIELDS, ethnicity="Not Hispanic or Latino",
                 race="White", sex="Female", age=42)
        r = GEN.generate_lar_record("APP-1", f, outcome="recommend")
        self.assertEqual(r["applicant_ethnicity"], 2)
        self.assertEqual(r["applicant_race"], 5)
        self.assertEqual(r["applicant_sex"], 2)
        self.assertEqual(r["applicant_age"], 42)
        self.assertTrue(r["demographic_data_provided"])

    def test_hispanic_and_male_and_black(self):
        f = dict(LOAN_FIELDS, ethnicity="Hispanic or Latino",
                 race="Black or African American", sex="Male")
        r = GEN.generate_lar_record("APP-1", f, outcome="recommend")
        self.assertEqual(r["applicant_ethnicity"], 1)
        self.assertEqual(r["applicant_race"], 3)
        self.assertEqual(r["applicant_sex"], 1)


class LoanDataTests(unittest.TestCase):
    def test_loan_and_income_populated(self):
        r = GEN.generate_lar_record("APP-1", LOAN_FIELDS, outcome="recommend",
                                    tenant_id="meridian")
        self.assertEqual(r["loan_amount"], 400000.0)
        self.assertEqual(r["loan_type"], "Conventional")
        self.assertEqual(r["applicant_income"], 120000.0)  # 10000 * 12
        self.assertEqual(r["tenant_id"], "meridian")
        self.assertEqual(r["lien_status"], 1)  # default first lien
        self.assertTrue(r["hmda_reportable"])
        self.assertIn("1003", r["citation"])

    def test_missing_loan_fields_are_none_not_invented(self):
        r = GEN.generate_lar_record("APP-1", {}, outcome="recommend")
        self.assertIsNone(r["loan_amount"])
        self.assertIsNone(r["applicant_income"])
        self.assertIsNone(r["property_type"])


if __name__ == "__main__":
    unittest.main()
