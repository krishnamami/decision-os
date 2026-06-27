"""Unit tests for P0-I LicenseComplianceChecker (pure, no DB).

SAFE Act state-licensing gate: licensed / unlicensed (block) / not_applicable.
16/16-safe guards (no property_state OR no licenses -> not_applicable) asserted.
RULE 11 throughout.
"""
import unittest
from datetime import date, timedelta

from core.compliance.license_checker import LicenseComplianceChecker

LICENSES = [
    {"state": "TX", "license_number": "ML-12345", "license_type": "Mortgage Lender",
     "expiry_date": "2099-12-31"},
    {"state": "CA", "license_number": "CA-99999", "license_type": "CFL",
     "expiry_date": "2099-06-30"},
]


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.c = LicenseComplianceChecker()

    def test_no_property_state_not_applicable(self):
        r = self.c.check(None, LICENSES, tenant_id="meridian")
        self.assertEqual(r["status"], "not_applicable")
        self.assertIsNone(r["licensed"])
        self.assertTrue(any("property_state" in m for m in r["missing_inputs"]))

    def test_no_licenses_not_applicable_with_warning(self):
        r = self.c.check("TX", [], tenant_id="meridian")
        self.assertEqual(r["status"], "not_applicable")
        self.assertIn("WARNING", r["note"])
        self.assertTrue(r["missing_inputs"])

    def test_meridian_both_guards_never_block(self):
        # meridian reality: no property_state AND no licenses -> not_applicable
        self.assertEqual(self.c.check(None, [], tenant_id="meridian")["status"], "not_applicable")


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.c = LicenseComplianceChecker()

    def test_licensed(self):
        r = self.c.check("TX", LICENSES, tenant_id="atlas")
        self.assertEqual(r["status"], "licensed")
        self.assertTrue(r["licensed"])
        self.assertEqual(r["license_count"], 1)

    def test_unlicensed_state(self):
        r = self.c.check("NY", LICENSES, tenant_id="atlas")
        self.assertEqual(r["status"], "unlicensed")
        self.assertFalse(r["licensed"])
        self.assertEqual(r["licensed_states"], ["CA", "TX"])
        self.assertIn("SAFE Act", r["regulatory_note"])

    def test_case_insensitive_state(self):
        for s in ("tx", "Tx", "TX", " tx "):
            self.assertEqual(self.c.check(s, LICENSES)["status"], "licensed")

    def test_expired_license_unlicensed(self):
        exp = [{"state": "FL", "license_number": "FL-111", "expiry_date": "2023-12-31"}]
        r = self.c.check("FL", exp, tenant_id="atlas", check_date="2026-06-27")
        self.assertEqual(r["status"], "unlicensed")
        self.assertTrue(r["expired_licenses"])

    def test_expiring_soon_flagged_not_blocked(self):
        # expires within 30 days -> still licensed, but flagged (no December crash)
        soon = (date(2026, 12, 20) + timedelta(days=10)).isoformat()  # 2026-12-30
        lic = [{"state": "TX", "license_number": "X", "expiry_date": soon}]
        r = self.c.check("TX", lic, check_date="2026-12-20")
        self.assertEqual(r["status"], "licensed")
        self.assertEqual(len(r["expiring_soon"]), 1)

    def test_no_expiry_date_treated_active(self):
        lic = [{"state": "TX", "license_number": "X"}]  # no expiry
        self.assertEqual(self.c.check("TX", lic)["status"], "licensed")

    def test_rule11_everywhere(self):
        for r in (self.c.check(None, []), self.c.check("TX", []),
                  self.c.check("TX", LICENSES), self.c.check("NY", LICENSES)):
            self.assertIn("data_source", r)
            self.assertIn("missing_inputs", r)
            self.assertIn("citation", r)


class BulkTests(unittest.TestCase):
    def setUp(self):
        self.c = LicenseComplianceChecker()

    def test_bulk_counts_and_blocked(self):
        loans = [{"application_id": "APP-01", "property_state": "TX"},
                 {"application_id": "APP-02", "property_state": "NY"},
                 {"application_id": "APP-03", "property_state": None}]
        out = self.c.check_bulk(loans, LICENSES, "atlas")
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["licensed"], 1)
        self.assertEqual(out["unlicensed"], 1)
        self.assertEqual(out["not_applicable"], 1)
        self.assertEqual(out["blocked_loans"], ["APP-02"])

    def test_bulk_reads_state_code_fallback(self):
        # CF-A/HMDA loans carry state_code, not property_state
        loans = [{"application_id": "A", "state_code": "TX"}]
        out = self.c.check_bulk(loans, LICENSES)
        self.assertEqual(out["licensed"], 1)

    def test_bulk_provenance(self):
        out = self.c.check_bulk([{"application_id": "A", "property_state": "NY"}], LICENSES)
        self.assertIn("data_source", out)
        self.assertIn("missing_inputs", out)


if __name__ == "__main__":
    unittest.main()
