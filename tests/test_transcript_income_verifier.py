"""Unit tests for FR-G TranscriptIncomeVerifier (pure, no DB).

Variance tiers reuse FR-B catalogue (medium=10, high=25, critical=50). Tier values
chosen to land unambiguously in each band. RULE 11 provenance on every output.
"""
import unittest

from core.fraud.transcript_income_verifier import (
    TRANSCRIPT_RULE_KEYS,
    TranscriptIncomeVerifier,
)


def _w2(wages, year=2024):
    return {"box1_wages": wages, "tax_year": year}


def _tr(wages=None, year=2024, **extra):
    d = {"tax_year": year}
    if wages is not None:
        d["wages_salaries"] = wages
    d.update(extra)
    return d


class W2VsTranscriptTests(unittest.TestCase):
    def setUp(self):
        self.v = TranscriptIncomeVerifier()

    def test_missing_inputs(self):
        r = self.v.verify_w2_vs_transcript({}, {})
        self.assertEqual(r["status"], "not_applicable")
        self.assertTrue(r["missing_inputs"])
        self.assertFalse(r["fraud_signal"])

    def test_year_mismatch(self):
        r = self.v.verify_w2_vs_transcript(_w2(96000, 2023), _tr(96000, 2024))
        self.assertEqual(r["status"], "year_mismatch")
        self.assertFalse(r["fraud_signal"])

    def test_match_within_tolerance(self):
        r = self.v.verify_w2_vs_transcript(_w2(102000), _tr(100000))  # 2%
        self.assertEqual(r["status"], "match")
        self.assertFalse(r["fraud_signal"])

    def test_medium(self):
        r = self.v.verify_w2_vs_transcript(_w2(115000), _tr(100000))  # 15%
        self.assertEqual(r["severity"], "medium")
        self.assertTrue(r["fraud_signal"])
        self.assertFalse(r["auto_block"])
        self.assertEqual(r["status"], "income_inflation")

    def test_high(self):
        r = self.v.verify_w2_vs_transcript(_w2(130000), _tr(100000))  # 30%
        self.assertEqual(r["severity"], "high")
        self.assertFalse(r["auto_block"])

    def test_critical_auto_block(self):
        r = self.v.verify_w2_vs_transcript(_w2(160000), _tr(100000))  # 60%
        self.assertEqual(r["severity"], "critical")
        self.assertTrue(r["auto_block"])
        self.assertTrue(r["docs_needed"])

    def test_understatement_direction(self):
        r = self.v.verify_w2_vs_transcript(_w2(70000), _tr(100000))  # 30% under
        self.assertEqual(r["status"], "income_understatement")
        self.assertFalse(r["inflation"])

    def test_irs_zero(self):
        r = self.v.verify_w2_vs_transcript(_w2(96000), _tr(0))
        self.assertEqual(r["status"], "zero_irs_income")
        self.assertEqual(r["severity"], "high")
        self.assertTrue(r["fraud_signal"])

    def test_custom_thresholds_flow(self):
        vc = TranscriptIncomeVerifier(rules={
            "income_mismatch_medium_pct": 5, "income_mismatch_high_pct": 15,
            "income_mismatch_critical_pct": 30})
        r = vc.verify_w2_vs_transcript(_w2(110000), _tr(100000))  # 10% -> medium @5%
        self.assertEqual(r["severity"], "medium")


class SeAndAgiTests(unittest.TestCase):
    def setUp(self):
        self.v = TranscriptIncomeVerifier()

    def test_se_missing(self):
        r = self.v.verify_se_vs_transcript({}, _tr())
        self.assertEqual(r["status"], "not_applicable")

    def test_se_match(self):
        r = self.v.verify_se_vs_transcript(
            {"net_profit": 50000, "tax_year": 2024},
            _tr(self_employment_income=51000))
        self.assertEqual(r["status"], "match")

    def test_se_critical(self):
        r = self.v.verify_se_vs_transcript(
            {"net_profit": 120000, "tax_year": 2024},
            _tr(self_employment_income=50000))
        self.assertEqual(r["severity"], "critical")

    def test_agi_no_income(self):
        r = self.v.verify_total_vs_agi(0, _tr(agi=100000))
        self.assertEqual(r["status"], "not_applicable")

    def test_agi_no_transcript(self):
        r = self.v.verify_total_vs_agi(8000, {})
        self.assertEqual(r["status"], "not_applicable")

    def test_agi_match(self):
        r = self.v.verify_total_vs_agi(8000, _tr(agi=100000))  # 96k vs 100k = 4%
        self.assertEqual(r["status"], "match")


class RunAllTests(unittest.TestCase):
    def setUp(self):
        self.v = TranscriptIncomeVerifier()

    def test_no_transcript_not_applicable(self):
        r = self.v.run_all_checks(w2_fields=_w2(96000))
        self.assertEqual(r["status"], "not_applicable")
        self.assertTrue(r["missing_inputs"])

    def test_fraud_detected_rollup(self):
        r = self.v.run_all_checks(
            w2_fields=_w2(160000),                       # 60% -> critical
            transcript_fields=_tr(100000, agi=100000),
            qualifying_monthly=8333.33)                  # ~100k vs agi 100k -> match
        self.assertEqual(r["status"], "fraud_detected")
        self.assertEqual(r["highest_severity"], "critical")
        self.assertTrue(r["auto_block"])
        self.assertGreaterEqual(r["checks_run"], 2)

    def test_clean_rollup(self):
        r = self.v.run_all_checks(
            w2_fields=_w2(101000), transcript_fields=_tr(100000))
        self.assertEqual(r["status"], "clean")
        self.assertFalse(r["auto_block"])


class Rule11Tests(unittest.TestCase):
    def test_provenance_everywhere(self):
        v = TranscriptIncomeVerifier()
        outs = [
            v.verify_w2_vs_transcript(_w2(160000), _tr(100000)),
            v.verify_w2_vs_transcript({}, {}),
            v.verify_se_vs_transcript({}, _tr()),
            v.verify_total_vs_agi(8000, _tr(agi=100000)),
            v.run_all_checks(),
        ]
        for o in outs:
            self.assertIn("data_source", o)
            self.assertIn("missing_inputs", o)
            self.assertIn("citation", o)

    def test_reuses_fr_b_keys(self):
        self.assertEqual(TRANSCRIPT_RULE_KEYS,
                         ["income_mismatch_medium_pct", "income_mismatch_high_pct",
                          "income_mismatch_critical_pct"])


if __name__ == "__main__":
    unittest.main()
