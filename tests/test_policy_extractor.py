"""Unit tests for PL-C CreditPolicyExtractor (pure, no DB, no API key).

Synthetic policy-text fixtures exercise the regex extraction → rules-schema mapping,
the VA-excluded products, the injected-Vision fallback, and RULE 11 provenance. Vision
is patched via an injected vision_call so nothing needs ANTHROPIC_API_KEY.
"""
import asyncio
import unittest

from core.extraction.policy_extractor import CreditPolicyExtractor

FULL_POLICY = b"""Credit Policy - Example Bank
Minimum credit score: 660 for conventional loans, 620 for FHA.
Maximum DTI: 43% for conventional loans.
Maximum LTV: 95% for purchase transactions.
Maximum loan amount: $2,500,000.
Minimum loan amount: $75,000.
Products: Conventional YES. FHA YES. VA NO. Jumbo YES.
Employment history: 24 months required.
"""

NO_LTV_POLICY = b"""Credit Policy
Minimum credit score: 700.
Maximum DTI: 40%.
Products: Conventional YES.
"""


def _run(coro):
    return asyncio.run(coro)


class PatternExtractTests(unittest.TestCase):
    def setUp(self):
        self.r = CreditPolicyExtractor()
        self.f = self.r._pattern_extract(FULL_POLICY.decode())

    def test_credit_min_score(self):
        self.assertEqual(self.f["credit.min_score"]["value"], 660.0)

    def test_dti_back_max(self):
        self.assertEqual(self.f["dti.back_max"]["value"], 43.0)

    def test_ltv_max(self):
        self.assertEqual(self.f["ltv.max"]["value"], 95.0)

    def test_loan_amounts(self):
        self.assertEqual(self.f["max_loan_amount"]["value"], 2500000.0)
        self.assertEqual(self.f["min_loan_amount"]["value"], 75000.0)

    def test_employment_months(self):
        self.assertEqual(self.f["income.employment_history_months"]["value"], 24.0)

    def test_employment_years_normalized(self):
        f = self.r._pattern_extract("Employment history: 2 years required.")
        self.assertEqual(f["income.employment_history_months"]["value"], 24.0)  # 2*12

    def test_products_va_excluded(self):
        progs = {p["product"]: p["offered"] for p in self.f["programs"]["value"]}
        self.assertTrue(progs["conventional"])
        self.assertFalse(progs["va"])

    def test_source_quotes_present(self):
        for k, v in self.f.items():
            self.assertIn("source_quote", v)


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.r = CreditPolicyExtractor()

    def test_proposal_shape(self):
        out = _run(self.r.extract(FULL_POLICY, "policy.pdf"))
        self.assertEqual(out["proposal"]["credit"]["min_score"], 660.0)
        self.assertEqual(out["proposal"]["dti"]["back_max"], 43.0)
        self.assertEqual(out["proposal"]["ltv"]["max"], 95.0)
        self.assertNotIn("va", out["proposal"]["programs"])
        self.assertIn("conventional", out["proposal"]["programs"])

    def test_overlay_updates(self):
        out = _run(self.r.extract(FULL_POLICY, "policy.pdf"))
        ov = {u["rule_type"]: u["overlay_value"] for u in out["overlay_updates"]}
        self.assertEqual(ov["credit_floor"], 660.0)
        self.assertEqual(ov["dti_back_max"], 43.0)
        self.assertEqual(ov["ltv_max_purchase"], 95.0)

    def test_complete_policy_regex_only(self):
        out = _run(self.r.extract(FULL_POLICY, "policy.pdf"))
        self.assertEqual(out["method"], "regex")   # all key fields found -> no Vision
        self.assertEqual(out["missing_inputs"], [])
        self.assertGreater(out["avg_confidence"], 0.7)

    def test_status_draft_never_activates(self):
        out = _run(self.r.extract(FULL_POLICY, "policy.pdf"))
        self.assertEqual(out["status"], "draft")
        self.assertIn("REVIEW REQUIRED", out["note"])

    def test_missing_key_field_surfaced(self):
        out = _run(self.r.extract(NO_LTV_POLICY, "policy.pdf"))
        self.assertTrue(any("ltv.max" in m for m in out["missing_inputs"]))


class VisionFallbackTests(unittest.TestCase):
    def test_vision_fills_missing_key_field(self):
        async def fake_vision(_bytes):
            return {"ltv.max": {"value": 90.0, "confidence": 0.9, "source_quote": "LTV 90"}}
        r = CreditPolicyExtractor(vision_call=fake_vision)
        out = _run(r.extract(NO_LTV_POLICY, "policy.pdf"))
        self.assertEqual(out["method"], "regex+vision")
        self.assertEqual(out["proposal"]["ltv"]["max"], 90.0)
        self.assertEqual(out["missing_inputs"], [])

    def test_vision_not_called_when_complete(self):
        async def boom(_bytes):
            raise AssertionError("vision must not run when regex found all key fields")
        r = CreditPolicyExtractor(vision_call=boom)
        out = _run(r.extract(FULL_POLICY, "policy.pdf"))
        self.assertEqual(out["method"], "regex")

    def test_vision_unavailable_degrades(self):
        # no vision_call + missing field -> stays missing, no crash
        r = CreditPolicyExtractor()
        out = _run(r.extract(NO_LTV_POLICY, "policy.pdf"))
        self.assertTrue(out["missing_inputs"])  # ltv.max still missing


class Rule11Tests(unittest.TestCase):
    def test_provenance(self):
        out = _run(CreditPolicyExtractor().extract(FULL_POLICY, "p.pdf"))
        self.assertIn("data_source", out)
        self.assertIn("missing_inputs", out)
        self.assertIsInstance(out["unmapped_items"], list)


if __name__ == "__main__":
    unittest.main()
