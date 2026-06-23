"""Unit tests for the RA-7A ATR/QM verifier (12 CFR 1026.43). Pure, no DB."""
import unittest

from core.compliance.atr_verifier import ATRVerifier, SAFE_DEFAULTS

# Catalogue thresholds (as the enricher would attach them).
RULES = {"atr_required_factors": 8, "qm_dti_max": 43.0,
         "qm_points_fees_max": 3.0, "hpml_threshold_bps": 150.0}

FULL_ENTITY = {
    "qualifying_monthly": 8000.0, "employment_verified": True,
    "piti_monthly": 2000.0, "monthly_obligations": 500.0,
    "dti_back": 38.0, "mid_credit_score": 740, "ltv": 80.0,
    "loan_amount": 400000.0, "interest_rate": 6.5,
}


class ATRVerifyTests(unittest.TestCase):
    def test_all_factors_present(self):
        r = ATRVerifier(RULES).verify(FULL_ENTITY)
        self.assertTrue(r["atr_satisfied"])
        self.assertEqual(r["factors_passed"], 8)
        self.assertEqual(r["factors_failed"], [])
        self.assertEqual(r["citation"], "12 CFR 1026.43(c)")

    def test_missing_income(self):
        e = dict(FULL_ENTITY, qualifying_monthly=None)
        r = ATRVerifier(RULES).verify(e)
        self.assertFalse(r["atr_satisfied"])
        self.assertIn("income_verified", r["factors_failed"])
        self.assertEqual(r["factors_passed"], 7)

    def test_missing_dti(self):
        e = dict(FULL_ENTITY, dti_back=None)
        r = ATRVerifier(RULES).verify(e)
        self.assertFalse(r["atr_satisfied"])
        self.assertIn("dti_computed", r["factors_failed"])

    def test_missing_employment(self):
        e = dict(FULL_ENTITY, employment_verified=False)
        r = ATRVerifier(RULES).verify(e)
        self.assertIn("employment_verified", r["factors_failed"])


class QMClassifyTests(unittest.TestCase):
    def test_safe_harbor(self):
        e = dict(FULL_ENTITY, dti_back=38, points_fees_pct=2.5)  # apor absent
        r = ATRVerifier(RULES).classify_qm(e)
        self.assertEqual(r["qm_classification"], "QM_SAFE_HARBOR")
        self.assertTrue(r["safe_harbor_protected"])

    def test_rebuttable_presumption_when_hpml(self):
        e = dict(FULL_ENTITY, dti_back=38, points_fees_pct=2.5,
                 interest_rate=7.0, apor_rate=5.0)  # 200 bps over APOR
        r = ATRVerifier(RULES).classify_qm(e)
        self.assertTrue(r["hpml_flag"])
        self.assertEqual(r["qm_classification"], "QM_REBUTTABLE_PRESUMPTION")
        self.assertTrue(r["safe_harbor_protected"])

    def test_non_qm_high_dti(self):
        e = dict(FULL_ENTITY, dti_back=48, points_fees_pct=2.5)
        r = ATRVerifier(RULES).classify_qm(e)
        self.assertEqual(r["qm_classification"], "NON_QM")
        self.assertFalse(r["safe_harbor_protected"])

    def test_non_qm_points_exceed(self):
        e = dict(FULL_ENTITY, dti_back=38, points_fees_pct=4.5)
        r = ATRVerifier(RULES).classify_qm(e)
        self.assertEqual(r["qm_classification"], "NON_QM")

    def test_missing_dti_is_not_safe_harbor(self):
        # No verified DTI -> cannot claim safe harbor (conservative).
        e = dict(FULL_ENTITY, dti_back=None, points_fees_pct=0)
        r = ATRVerifier(RULES).classify_qm(e)
        self.assertFalse(r["dti_check"]["data_available"])
        self.assertFalse(r["dti_check"]["passes"])
        self.assertEqual(r["qm_classification"], "NON_QM")

    def test_dti_exactly_at_max_passes(self):
        e = dict(FULL_ENTITY, dti_back=43, points_fees_pct=0)
        r = ATRVerifier(RULES).classify_qm(e)
        self.assertTrue(r["dti_check"]["passes"])
        self.assertEqual(r["qm_classification"], "QM_SAFE_HARBOR")


class ThresholdSourceTests(unittest.TestCase):
    def test_catalogue_rules_used(self):
        v = ATRVerifier({"qm_dti_max": 45.0})
        self.assertEqual(v.qm_dti_max, 45.0)  # catalogue value, not the default

    def test_safe_defaults_when_no_rules(self):
        v = ATRVerifier()
        self.assertEqual(v.qm_dti_max, SAFE_DEFAULTS["qm_dti_max"])
        self.assertEqual(v.required_factors, SAFE_DEFAULTS["atr_required_factors"])

    def test_none_rule_falls_back_per_key(self):
        v = ATRVerifier({"qm_dti_max": None, "qm_points_fees_max": 2.0})
        self.assertEqual(v.qm_dti_max, SAFE_DEFAULTS["qm_dti_max"])  # None -> default
        self.assertEqual(v.qm_points_fees_max, 2.0)                  # provided value


if __name__ == "__main__":
    unittest.main()
