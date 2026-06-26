"""Unit tests for PL-A onboarding-step helpers (pure, no DB, no API key).

The 4 new onboarding endpoints (company / licenses / exception-config / test-loan)
keep their validation + normalization in pure module-level helpers so they are
testable without a live DB (the endpoints are thin DB wrappers). These tests cover
those helpers + the advisory test-loan probe (ProgramRecommender, no writes).
RULE 11 provenance asserted on the probe.
"""
import unittest

from api.accord.onboarding import (
    advise_test_loan,
    build_company_update,
    synthetic_test_profile,
    validate_exception_config,
    validate_licenses,
)


class CompanyTests(unittest.TestCase):
    def test_valid(self):
        name, patch, errors = build_company_update({
            "company_name": "Meridian Home Loans", "nmls_id": "123456",
            "contact_email": "ops@meridian.com", "primary_state": "ca",
            "company_type": "imc"})
        self.assertEqual(errors, [])
        self.assertEqual(name, "Meridian Home Loans")
        self.assertEqual(patch["nmls_id"], "123456")
        self.assertEqual(patch["primary_state"], "CA")  # upper-cased
        self.assertEqual(patch["company_type"], "imc")

    def test_missing_company_name(self):
        _, _, errors = build_company_update({"nmls_id": "123456"})
        self.assertTrue(any("company_name" in e for e in errors))

    def test_missing_nmls(self):
        _, _, errors = build_company_update({"company_name": "X"})
        self.assertTrue(any("nmls_id" in e for e in errors))

    def test_bad_email(self):
        _, _, errors = build_company_update(
            {"company_name": "X", "nmls_id": "1", "contact_email": "notanemail"})
        self.assertTrue(any("contact_email" in e for e in errors))

    def test_bad_state(self):
        _, _, errors = build_company_update(
            {"company_name": "X", "nmls_id": "1", "primary_state": "ZZ"})
        self.assertTrue(any("primary_state" in e for e in errors))

    def test_unknown_company_type_defaults_other(self):
        _, patch, errors = build_company_update(
            {"company_name": "X", "nmls_id": "1", "company_type": "hedge_fund"})
        self.assertEqual(errors, [])
        self.assertEqual(patch["company_type"], "other")


class LicenseTests(unittest.TestCase):
    def test_valid(self):
        lic, errors, warnings = validate_licenses({"licenses": [
            {"state": "ca", "license_number": "CA-123"},
            {"state": "TX", "license_number": "TX-456", "license_type": "broker"}]})
        self.assertEqual(errors, [])
        self.assertEqual(len(lic), 2)
        self.assertEqual({x["state"] for x in lic}, {"CA", "TX"})
        self.assertEqual(lic[1]["license_type"], "broker")

    def test_empty_list(self):
        _, errors, _ = validate_licenses({"licenses": []})
        self.assertTrue(errors)

    def test_not_a_list(self):
        _, errors, _ = validate_licenses({"licenses": "CA"})
        self.assertTrue(errors)

    def test_missing_number(self):
        _, errors, _ = validate_licenses({"licenses": [{"state": "CA"}]})
        self.assertTrue(any("license_number" in e for e in errors))

    def test_bad_state_is_warning_not_error(self):
        lic, errors, warnings = validate_licenses(
            {"licenses": [{"state": "ZZ", "license_number": "X"}]})
        self.assertEqual(errors, [])
        self.assertTrue(warnings)
        self.assertEqual(len(lic), 1)  # still recorded

    def test_dedup_by_state_last_wins(self):
        lic, _, _ = validate_licenses({"licenses": [
            {"state": "CA", "license_number": "OLD"},
            {"state": "CA", "license_number": "NEW"}]})
        self.assertEqual(len(lic), 1)
        self.assertEqual(lic[0]["license_number"], "NEW")


class ExceptionConfigTests(unittest.TestCase):
    def test_valid(self):
        cfg, errors = validate_exception_config({
            "max_exception_level": 3, "auto_escalate_dti_threshold": 50.0,
            "auto_escalate_ltv_threshold": 97.0, "required_compensating_factors": 2,
            "exception_approval_roles": ["manager", "senior_uw"]})
        self.assertEqual(errors, [])
        self.assertEqual(cfg["max_exception_level"], 3)
        self.assertEqual(cfg["auto_escalate_dti_threshold"], 50.0)
        self.assertEqual(cfg["required_compensating_factors"], 2)

    def test_level_out_of_range(self):
        _, errors = validate_exception_config({"max_exception_level": 5})
        self.assertTrue(any("between 1 and 4" in e for e in errors))

    def test_missing_level(self):
        _, errors = validate_exception_config({"auto_escalate_dti_threshold": 50})
        self.assertTrue(any("max_exception_level is required" in e for e in errors))

    def test_dti_above_agency_ceiling(self):
        _, errors = validate_exception_config(
            {"max_exception_level": 2, "auto_escalate_dti_threshold": 65})
        self.assertTrue(any("60%" in e for e in errors))

    def test_ltv_above_100(self):
        _, errors = validate_exception_config(
            {"max_exception_level": 2, "auto_escalate_ltv_threshold": 105})
        self.assertTrue(any("100%" in e for e in errors))

    def test_cf_out_of_range(self):
        _, errors = validate_exception_config(
            {"max_exception_level": 2, "required_compensating_factors": 9})
        self.assertTrue(any("between 0 and 6" in e for e in errors))

    def test_bad_roles_type(self):
        _, errors = validate_exception_config(
            {"max_exception_level": 2, "exception_approval_roles": "manager"})
        self.assertTrue(any("list of role" in e for e in errors))


class TestLoanProbeTests(unittest.TestCase):
    def test_clean_approval_recommends(self):
        out = advise_test_loan(synthetic_test_profile("clean_approval"))
        self.assertEqual(out["outcome"], "recommend")
        self.assertTrue(out["eligible_products"])

    def test_fraud_profile_not_recommend(self):
        out = advise_test_loan(synthetic_test_profile("fraud"))
        self.assertIn(out["outcome"], ("block", "escalate"))

    def test_always_advisory_no_write(self):
        out = advise_test_loan(synthetic_test_profile("borderline"))
        self.assertTrue(out["advisory"])
        self.assertFalse(out["writes_decision_outputs"])
        self.assertIn("Advisory", out["note"])

    def test_does_not_claim_14_personas(self):
        out = advise_test_loan(synthetic_test_profile("clean_approval"))
        self.assertIn("ProgramRecommender", out["engine"])

    def test_rule11_provenance(self):
        out = advise_test_loan(synthetic_test_profile("clean_approval"))
        self.assertIn("data_source", out)
        self.assertIn("missing_inputs", out)

    def test_unknown_scenario_defaults_clean(self):
        self.assertEqual(synthetic_test_profile("nonsense"),
                         synthetic_test_profile("clean_approval"))


if __name__ == "__main__":
    unittest.main()
