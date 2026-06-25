"""Unit tests for the EV-G StalenessChecker (pure, no DB).

Covers fresh / stale / not_checkable per doc type, the RULE 11 provenance
(data_source + missing_inputs), the received_at-is-never-a-proxy guarantee, and
that thresholds flow from the injected catalogue rules.
"""
import unittest
from datetime import datetime

from core.evidence.staleness_checker import StalenessChecker, STALENESS_RULE_KEYS

NOW_YEAR = datetime.now().year
CLOSE = "2026-07-15"


class AppraisalTests(unittest.TestCase):
    def setUp(self):
        self.c = StalenessChecker()

    def test_fresh_within_120(self):
        r = self.c.check_appraisal({"effective_date": "2026-05-15"}, CLOSE)  # 61d
        self.assertEqual(r["status"], "fresh")
        self.assertEqual(r["age_days"], 61)
        self.assertEqual(r["missing_inputs"], [])

    def test_stale_past_120(self):
        r = self.c.check_appraisal({"effective_date": "2026-01-01"}, CLOSE)  # ~195d
        self.assertEqual(r["status"], "stale")
        self.assertTrue(r["docs_needed"])

    def test_fha_uses_180(self):
        # 150 days: stale for conv (120), fresh for fha (180)
        f = {"effective_date": "2026-02-15"}
        self.assertEqual(self.c.check_appraisal(f, CLOSE, "conventional")["status"], "stale")
        self.assertEqual(self.c.check_appraisal(f, CLOSE, "fha")["status"], "fresh")

    def test_no_effective_date_not_checkable(self):
        r = self.c.check_appraisal({}, CLOSE)
        self.assertEqual(r["status"], "not_checkable")
        self.assertTrue(r["missing_inputs"])

    def test_unparseable_date_not_checkable(self):
        r = self.c.check_appraisal({"effective_date": "garbage"}, CLOSE)
        self.assertEqual(r["status"], "not_checkable")


class PaystubTests(unittest.TestCase):
    def setUp(self):
        self.c = StalenessChecker()

    def test_fresh_within_30(self):
        r = self.c.check_paystub({"pay_period_end": "2026-06-20"}, CLOSE)  # 25d
        self.assertEqual(r["status"], "fresh")

    def test_stale_past_30(self):
        r = self.c.check_paystub({"pay_period_end": "2026-05-31"}, CLOSE)  # 45d
        self.assertEqual(r["status"], "stale")
        self.assertEqual(r["age_days"], 45)

    def test_no_period_end_not_checkable(self):
        self.assertEqual(self.c.check_paystub({}, CLOSE)["status"], "not_checkable")

    def test_custom_threshold_flows(self):
        c = StalenessChecker(rules={"paystub_max_age_days": 10})
        r = c.check_paystub({"pay_period_end": "2026-06-20"}, CLOSE)  # 25d > 10
        self.assertEqual(r["status"], "stale")
        self.assertEqual(r["max_days"], 10)


class TaxYearTests(unittest.TestCase):
    def setUp(self):
        self.c = StalenessChecker()

    def test_w2_current_year_fresh(self):
        r = self.c.check_w2({"tax_year": NOW_YEAR - 1})
        self.assertEqual(r["status"], "fresh")

    def test_w2_too_old_stale(self):
        r = self.c.check_w2({"tax_year": NOW_YEAR - 5})
        self.assertEqual(r["status"], "stale")
        self.assertTrue(r["docs_needed"])

    def test_w2_no_tax_year_not_checkable(self):
        self.assertEqual(self.c.check_w2({})["status"], "not_checkable")

    def test_tax_return_uses_lookback(self):
        r = self.c.check_tax_return({"tax_year": NOW_YEAR - 1}, "SCHEDULE_E")
        self.assertEqual(r["status"], "fresh")
        self.assertEqual(r["doc_type"], "SCHEDULE_E")


class RateLockHoiTests(unittest.TestCase):
    def setUp(self):
        self.c = StalenessChecker()

    def test_rate_lock_valid_when_expiry_after_close(self):
        r = self.c.check_rate_lock({"lock_expiry": "2026-08-01"}, CLOSE)
        self.assertEqual(r["status"], "fresh")
        self.assertGreaterEqual(r["days_to_expiry"], 0)

    def test_rate_lock_stale_when_expiry_before_close(self):
        r = self.c.check_rate_lock({"lock_expiry": "2026-06-19"}, CLOSE)
        self.assertEqual(r["status"], "stale")
        self.assertTrue(r["docs_needed"])

    def test_hoi_current_vs_expired(self):
        self.assertEqual(self.c.check_hoi({"expiration_date": "2027-01-01"}, CLOSE)["status"], "fresh")
        self.assertEqual(self.c.check_hoi({"expiration_date": "2026-06-01"}, CLOSE)["status"], "stale")


class NotCheckableTests(unittest.TestCase):
    def setUp(self):
        self.c = StalenessChecker()

    def test_credit_report_always_not_checkable_with_received_at_warning(self):
        r = self.c.check_credit_report({"mid_score": 720})
        self.assertEqual(r["status"], "not_checkable")
        self.assertTrue(any("received_at" in m for m in r["missing_inputs"]))

    def test_bank_statement_always_not_checkable(self):
        r = self.c.check_bank_statement({"ending_balance": 1000})
        self.assertEqual(r["status"], "not_checkable")
        self.assertTrue(any("received_at" in m for m in r["missing_inputs"]))


class CheckAllTests(unittest.TestCase):
    def test_counts_and_provenance(self):
        c = StalenessChecker()
        docs = {
            "APPRAISAL_URAR": {"effective_date": "2026-05-15"},   # fresh
            "PAYSTUB_CURRENT": {"pay_period_end": "2026-05-31"},   # stale (45d)
            "W2_CURRENT": {"tax_year": NOW_YEAR},                   # fresh
            "RATE_LOCK": {"lock_expiry": "2026-06-19"},            # stale (before close)
            "HOI_BINDER": {"expiration_date": "2027-01-01"},       # fresh
            "CREDIT_REPORT": {"mid_score": 700},                   # not_checkable
            "BANK_STATEMENT_M1": {"ending_balance": 5000},         # not_checkable
        }
        r = c.check_all(docs, CLOSE)
        self.assertEqual(r["stale_count"], 2)
        self.assertEqual(r["not_checkable_count"], 2)
        self.assertEqual(r["fresh_count"], 3)
        self.assertTrue(r["has_stale"])
        self.assertIn("PAYSTUB_CURRENT", r["stale_doc_types"])
        self.assertIn("RATE_LOCK", r["stale_doc_types"])
        self.assertIn("data_source", r)
        for check in r["checks"]:
            self.assertIn("data_source", check)
            self.assertIn("missing_inputs", check)

    def test_rule_keys_exported(self):
        self.assertIn("appraisal_validity_days_conventional", STALENESS_RULE_KEYS)
        self.assertEqual(len(STALENESS_RULE_KEYS), 7)


if __name__ == "__main__":
    unittest.main()
