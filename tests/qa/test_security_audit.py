"""QA-C — platform security audit tests (pure, no DB).

Drives the pure assess() with synthetic catalog facts: RLS coverage math, the
bypassrls headline finding, PII/encryption controls, and the verifiable-vs-
manual_review split.
"""
import unittest

from core.qa.security_audit import (
    STATUS_ATTENTION,
    STATUS_MANUAL,
    STATUS_PASS,
    SecurityAuditor,
)

BASE_FACTS = {
    "policies": [{"tablename": "decision_outputs", "policyname": "rls_do", "cmd": "ALL"},
                 {"tablename": "entity_states", "policyname": "rls_es", "cmd": "ALL"},
                 {"tablename": "overlay_rules", "policyname": "rls_ov", "cmd": "ALL"}],
    "rls_enabled_tables": ["decision_outputs", "entity_states", "overlay_rules", "products"],
    "app_role": "edms_admin", "app_role_superuser": False, "app_role_bypassrls": True,
    "pii_fields": ["ssn", "dob", "bank_account"], "s3_encryption": "AES256",
    "parameterized_queries": True,
}


def _ctrl(report, cid):
    return next(c for c in report["controls"] if c["id"] == cid)


class RlsCoverageTests(unittest.TestCase):
    def test_coverage_math(self):
        cov = SecurityAuditor()._rls_coverage(BASE_FACTS)
        self.assertEqual(cov["policy_count"], 3)
        self.assertEqual(sorted(cov["enforced_tables"]),
                         ["decision_outputs", "entity_states", "overlay_rules"])
        # products has RLS enabled but no policy
        self.assertEqual(cov["rls_enabled_without_policy"], ["products"])


class BypassFindingTests(unittest.TestCase):
    def test_bypassrls_is_headline_finding(self):
        r = SecurityAuditor().assess(BASE_FACTS)
        self.assertEqual(r["status"], "findings_present")
        self.assertTrue(r["app_role_bypassrls"])
        cc61 = _ctrl(r, "CC6.1")
        self.assertEqual(cc61["status"], STATUS_ATTENTION)
        self.assertIn("bypassrls", cc61["evidence"].lower())
        self.assertIn("remediation", cc61)
        # OWASP A05 misconfiguration also flags it
        self.assertEqual(_ctrl(r, "A05")["status"], STATUS_ATTENTION)

    def test_clean_role_passes(self):
        facts = {**BASE_FACTS, "app_role_bypassrls": False, "app_role_superuser": False}
        r = SecurityAuditor().assess(facts)
        self.assertEqual(_ctrl(r, "CC6.1")["status"], STATUS_PASS)
        self.assertEqual(_ctrl(r, "A05")["status"], STATUS_PASS)


class ControlStatusTests(unittest.TestCase):
    def setUp(self):
        self.r = SecurityAuditor().assess(BASE_FACTS)

    def test_pii_pass_when_classified(self):
        self.assertEqual(_ctrl(self.r, "CC6.7")["status"], STATUS_PASS)

    def test_injection_pass_with_params(self):
        self.assertEqual(_ctrl(self.r, "A03")["status"], STATUS_PASS)

    def test_injection_attention_without_params(self):
        r = SecurityAuditor().assess({**BASE_FACTS, "parameterized_queries": False})
        self.assertEqual(_ctrl(r, "A03")["status"], STATUS_ATTENTION)

    def test_infra_controls_manual_review(self):
        self.assertEqual(_ctrl(self.r, "CC6.6")["status"], STATUS_MANUAL)
        self.assertEqual(_ctrl(self.r, "A09")["status"], STATUS_MANUAL)

    def test_summary_counts(self):
        s = self.r["summary"]
        self.assertEqual(s["total_controls"], len(self.r["controls"]))
        self.assertEqual(s["attention"], self.r["findings_count"])
        self.assertEqual(s["manual_review"], self.r["manual_review_count"])

    def test_manual_not_auto_passed(self):
        # the honest posture: process controls are manual_review, never silent pass
        self.assertGreater(self.r["manual_review_count"], 0)
        self.assertTrue(self.r["missing_inputs"])

    def test_provenance(self):
        self.assertIn("data_source", self.r)
        self.assertIn("SOC 2", self.r["citation"])
        self.assertIn("posture report", self.r["note"])


if __name__ == "__main__":
    unittest.main()
