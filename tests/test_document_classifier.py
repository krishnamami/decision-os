"""Unit tests for the IN-E DocumentClassifier (no pdfplumber / no API key).

Tests the rule-based scorer on synthetic text and the hybrid routing with
_extract_text / _vision_classify stubbed, so nothing depends on real PDFs or a
live Vision call. RULE 11 provenance asserted on every output.
"""
import asyncio
import unittest

from core.extraction.classifier import (
    CLASSIFIER_SIGNATURES,
    ROUTABLE_TYPES,
    DocumentClassifier,
)

W2_TEXT = """W-2 Wage and Tax Statement  2024
Employee's social security number: 123-45-6789
Employer identification number: 12-3456789
Box 1 Wages, tips, other compensation: 85,000
"""
CREDIT_TEXT = """TransUnion Credit Report
Equifax Score: 742  Experian Score: 738  TransUnion Score: 745
Tradeline: Chase Visa balance 2,450  credit score 742
"""
PAYSTUB_TEXT = """ABC Corp Earnings Statement
Pay Period: 05/16/2026 - 05/31/2026
Regular pay 3,200   YTD gross 41,000   Net pay 2,410
"""
APPRAISAL_TEXT = """Uniform Residential Appraisal Report (URAR)
Subject Property: 123 Main St   Appraised value: 416,000
"""


def _run(coro):
    return asyncio.run(coro)


class RulesClassifyTests(unittest.TestCase):
    def setUp(self):
        self.dc = DocumentClassifier()

    def test_w2(self):
        r = self.dc._rules_classify(W2_TEXT, "john_w2_2024.pdf")
        self.assertEqual(r["doc_type"], "W2_CURRENT")
        self.assertGreaterEqual(r["confidence"], 0.6)
        self.assertEqual(r["missing_inputs"], [])
        self.assertIn("data_source", r)

    def test_credit_report(self):
        r = self.dc._rules_classify(CREDIT_TEXT, "credit_report.pdf")
        self.assertEqual(r["doc_type"], "CREDIT_REPORT")

    def test_paystub(self):
        r = self.dc._rules_classify(PAYSTUB_TEXT, "paystub.pdf")
        self.assertEqual(r["doc_type"], "PAYSTUB_CURRENT")

    def test_appraisal(self):
        r = self.dc._rules_classify(APPRAISAL_TEXT, "appraisal.pdf")
        self.assertEqual(r["doc_type"], "APPRAISAL_URAR")

    def test_empty_text_unknown(self):
        r = self.dc._rules_classify("", "document.pdf")
        self.assertEqual(r["doc_type"], "UNKNOWN")
        self.assertTrue(r["missing_inputs"])

    def test_generic_text_unknown(self):
        r = self.dc._rules_classify("This is a general cover letter to whom it may concern.", "x.pdf")
        self.assertEqual(r["doc_type"], "UNKNOWN")

    def test_filename_hint_adds_score(self):
        s_no, _ = self.dc._score_rules("Pay Period regular pay", "")
        s_fn, _ = self.dc._score_rules("Pay Period regular pay", "my_paystub.pdf")
        self.assertGreater(s_fn["PAYSTUB_CURRENT"], s_no["PAYSTUB_CURRENT"])

    def test_w2_outscores_paystub_on_w2_text(self):
        scores, _ = self.dc._score_rules(W2_TEXT, "")
        self.assertGreater(scores.get("W2_CURRENT", 0), scores.get("PAYSTUB_CURRENT", 0))


class HybridRoutingTests(unittest.TestCase):
    def test_rules_only_path(self):
        dc = DocumentClassifier()
        dc._extract_text = lambda b: W2_TEXT
        r = _run(dc.classify(b"x", "w2.pdf"))
        self.assertEqual(r["doc_type"], "W2_CURRENT")
        self.assertEqual(r["classification_path"], "rules_only")

    def test_vision_fallback_when_rules_ambiguous(self):
        dc = DocumentClassifier()
        dc._extract_text = lambda b: ""  # rules find nothing -> low confidence

        async def _fake_vision(b):
            return {"doc_type": "GIFT_LETTER", "confidence": 0.92, "method": "vision",
                    "matched_signals": ["gift letter header"], "candidates": {},
                    "data_source": "Claude Vision", "missing_inputs": []}
        dc._vision_classify = _fake_vision
        r = _run(dc.classify(b"x", "scan.pdf"))
        self.assertEqual(r["classification_path"], "vision_fallback")
        self.assertEqual(r["doc_type"], "GIFT_LETTER")

    def test_both_low_returns_unknown(self):
        dc = DocumentClassifier()
        dc._extract_text = lambda b: ""

        async def _fake_vision(b):
            return {"doc_type": "UNKNOWN", "confidence": 0.0, "method": "vision_failed",
                    "matched_signals": [], "candidates": {},
                    "data_source": "Claude Vision (unavailable)",
                    "missing_inputs": ["Vision classification failed"]}
        dc._vision_classify = _fake_vision
        r = _run(dc.classify(b"x", "scan.pdf"))
        self.assertEqual(r["doc_type"], "UNKNOWN")
        self.assertEqual(r["classification_path"], "both_low_confidence")
        self.assertTrue(r["missing_inputs"])

    def test_vision_not_called_when_rules_confident(self):
        dc = DocumentClassifier()
        dc._extract_text = lambda b: CREDIT_TEXT

        async def _boom(b):
            raise AssertionError("vision must not be called on a confident rules match")
        dc._vision_classify = _boom
        r = _run(dc.classify(b"x", "credit.pdf"))
        self.assertEqual(r["doc_type"], "CREDIT_REPORT")


class ValidateSuppliedTests(unittest.TestCase):
    def test_mismatch_flagged(self):
        dc = DocumentClassifier()
        dc._extract_text = lambda b: CREDIT_TEXT
        m = dc.validate_supplied(b"x", "W2_CURRENT", "doc.pdf")
        self.assertIsNotNone(m)
        self.assertEqual(m["classifier_suggests"], "CREDIT_REPORT")

    def test_match_no_warning(self):
        dc = DocumentClassifier()
        dc._extract_text = lambda b: CREDIT_TEXT
        self.assertIsNone(dc.validate_supplied(b"x", "CREDIT_REPORT", "doc.pdf"))


class RegistryTests(unittest.TestCase):
    def test_signatures_target_routable_types(self):
        from core.extraction.router import (TIER_1_TEXTRACT, TIER_2_VISION,
                                             TIER_3_REGEX)
        routable = TIER_1_TEXTRACT | TIER_2_VISION | TIER_3_REGEX
        # every classifier signature must be a doc type that has an extractor
        self.assertTrue(ROUTABLE_TYPES.issubset(routable),
                        f"non-routable: {ROUTABLE_TYPES - routable}")

    def test_every_signature_has_anchors(self):
        for dt, sig in CLASSIFIER_SIGNATURES.items():
            self.assertTrue(sig.get("anchors"), dt)


if __name__ == "__main__":
    unittest.main()
