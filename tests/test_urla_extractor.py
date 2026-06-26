"""Unit tests for MI-D URLAExtractor (pure, no DB, no API key).

The hybrid 1003 extractor: pdfplumber-text regex (digital 1003) + an injected
Vision fallback (scanned paper / checkboxes). _extract_text is patched so no real
PDF is needed; the Vision call is injected so nothing needs ANTHROPIC_API_KEY.
RULE 11: confidence + warnings for missing fields (never fabricated).
"""
import asyncio
import unittest
from unittest import mock

from core.extraction.urla_extractor import URLAExtractor, URLA_PATTERNS

# A digital-1003 text layer carrying all 8 loan-level fields.
FULL_URLA = (
    "Uniform Residential Loan Application "
    "Base Loan Amount $400,000 Purchase Price 500,000 "
    "Mortgage Type: Conventional Purpose of Loan: Purchase "
    "Occupancy: Primary Residence Property Type: Condo "
    "Property State: CA Number of Units: 1 "
    "123 Main St, Los Angeles CA 90012"
)

# A scanned form: no text layer at all (pdfplumber returns "") -> Vision only.
SCANNED_URLA = ""


def _run(coro):
    return asyncio.run(coro)


class PatternExtractTests(unittest.TestCase):
    def setUp(self):
        self.r = URLAExtractor()
        self.f = self.r._pattern_extract(FULL_URLA)

    def test_loan_amount(self):
        self.assertEqual(self.f["loan_amount"], 400000.0)

    def test_purchase_price(self):
        self.assertEqual(self.f["purchase_price"], 500000.0)

    def test_loan_type_normalized(self):
        self.assertEqual(self.f["loan_type"], "conventional")

    def test_loan_purpose_normalized(self):
        self.assertEqual(self.f["loan_purpose"], "purchase")

    def test_occupancy_normalized(self):
        self.assertEqual(self.f["occupancy_type"], "primary")

    def test_property_type_normalized(self):
        self.assertEqual(self.f["property_type"], "condo")

    def test_property_state(self):
        self.assertEqual(self.f["property_state"], "CA")

    def test_number_of_units(self):
        self.assertEqual(self.f["number_of_units"], 1)

    def test_all_eight_fields(self):
        self.assertEqual(set(self.f), set(URLA_PATTERNS))


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        self.r = URLAExtractor()

    def test_conv_abbreviation(self):
        f = self.r._pattern_extract("Loan Type: Conv")
        self.assertEqual(f["loan_type"], "conventional")

    def test_cash_out(self):
        f = self.r._pattern_extract("Purpose of Loan: Cash-Out Refinance")
        self.assertEqual(f["loan_purpose"], "cash_out_refinance")

    def test_principal_is_primary(self):
        f = self.r._pattern_extract("Occupancy: Principal Residence")
        self.assertEqual(f["occupancy_type"], "primary")

    def test_investment(self):
        f = self.r._pattern_extract("Occupancy Type: Investment")
        self.assertEqual(f["occupancy_type"], "investment")

    def test_2_4_unit(self):
        f = self.r._pattern_extract("Property Type: 2-4 Unit Number of Units: 3")
        self.assertEqual(f["property_type"], "multi_unit")
        self.assertEqual(f["number_of_units"], 3)


class HybridExtractTests(unittest.TestCase):
    def _extract(self, text, vision_call=None):
        r = URLAExtractor(vision_call=vision_call)
        with mock.patch.object(URLAExtractor, "_extract_text", return_value=text):
            return _run(r.extract(b"%PDF-fake", "URLA_1003"))

    def test_digital_text_no_vision(self):
        async def boom(_b):
            raise AssertionError("vision must not run when text has all key fields")
        r = self._extract(FULL_URLA, vision_call=boom)
        self.assertEqual(r.method, "pdfplumber")
        self.assertEqual(r.fields["loan_amount"], 400000.0)
        self.assertEqual(r.confidence, 1.0)
        self.assertEqual(r.warnings, [])

    def test_scanned_falls_back_to_vision(self):
        async def fake_vision(_b):
            return {"loan_amount": 350000, "loan_type": "fha", "loan_purpose": "purchase",
                    "occupancy_type": "primary", "property_type": "single_family"}
        r = self._extract(SCANNED_URLA, vision_call=fake_vision)
        self.assertEqual(r.method, "vision")
        self.assertEqual(r.fields["loan_amount"], 350000.0)
        self.assertEqual(r.fields["loan_type"], "fha")

    def test_vision_fills_only_missing(self):
        # text has loan_amount; vision supplies the missing key fields
        text = "Base Loan Amount 425000"
        async def fake_vision(_b):
            return {"loan_amount": 999999,  # must NOT override the text value
                    "loan_type": "va", "loan_purpose": "purchase", "occupancy_type": "primary"}
        r = self._extract(text, vision_call=fake_vision)
        self.assertEqual(r.method, "pdfplumber+vision")
        self.assertEqual(r.fields["loan_amount"], 425000.0)  # text wins
        self.assertEqual(r.fields["loan_type"], "va")

    def test_no_key_no_vision_degrades(self):
        # scanned + no vision_call (and no API key) -> regex-only, warnings, no crash
        r = self._extract(SCANNED_URLA)
        self.assertIn(r.method, ("pdfplumber", "vision"))
        self.assertTrue(r.warnings)
        self.assertLess(r.confidence, 1.0)

    def test_missing_fields_in_warnings(self):
        r = self._extract("Base Loan Amount 400000")  # only 1 of 8
        self.assertTrue(any("loan_type" in w for w in r.warnings))
        self.assertEqual(r.fields["loan_amount"], 400000.0)

    def test_corrupt_pdf_does_not_crash(self):
        # _extract_text raises -> text="" -> graceful (regex-only, no key)
        r = URLAExtractor()
        with mock.patch.object(URLAExtractor, "_extract_text", side_effect=Exception("bad pdf")):
            res = _run(r.extract(b"junk", "URLA_1003"))
        self.assertEqual(res.fields, {})
        self.assertTrue(res.warnings)


class RouterTests(unittest.TestCase):
    def test_route_urla_uses_hybrid_extractor(self):
        from core.extraction.router import route_extraction, tier_for
        with mock.patch.object(URLAExtractor, "_extract_text", return_value=FULL_URLA):
            r = _run(route_extraction(b"%PDF-fake", "URLA_1003"))
        self.assertEqual(r.fields["loan_type"], "conventional")
        self.assertEqual(r.fields["occupancy_type"], "primary")
        # still classified text-first for routing/tier introspection
        self.assertEqual(tier_for("URLA_1003"), "textract")


if __name__ == "__main__":
    unittest.main()
