"""Unit tests for the RA-EX-D extraction pipeline. No real Vision API calls —
the anthropic client is mocked."""
import asyncio
import types
import unittest
from unittest import mock

from core.extraction.base import ExtractionResult
from core.extraction.router import route_extraction, tier_for
from core.extraction.vision_extractor import VisionExtractor


def _run(coro):
    return asyncio.run(coro)


class RouterTests(unittest.TestCase):
    def test_tier_for(self):
        self.assertEqual(tier_for("PURCHASE_AGREEMENT"), "vision")
        self.assertEqual(tier_for("APPRAISAL_URAR"), "vision")
        self.assertEqual(tier_for("W2_CURRENT"), "textract")
        self.assertEqual(tier_for("FLOOD_CERT"), "regex")
        self.assertEqual(tier_for("CREDIT_REPORT"), "regex")
        self.assertIsNone(tier_for("SOMETHING_UNKNOWN"))

    def test_route_unknown_returns_warning_not_error(self):
        r = _run(route_extraction(b"", "SOMETHING_UNKNOWN"))
        self.assertEqual(r.method, "unknown")
        self.assertEqual(r.fields, {})
        self.assertTrue(r.warnings)

    def test_route_textract_is_real(self):
        # W2 routes to the pdfplumber Tier-1 extractor; non-PDF bytes -> error
        # method (proves it's no longer a stub).
        r = _run(route_extraction(b"x", "W2_CURRENT"))
        self.assertEqual(r.method, "pdfplumber_error")

    def test_route_regex_is_real(self):
        # FLOOD_CERT routes to the real Tier-3 regex extractor over text bytes.
        r = _run(route_extraction(b"Flood Zone AE Community 120100", "FLOOD_CERT"))
        self.assertEqual(r.method, "regex")
        self.assertEqual(r.fields["flood_zone"], "AE")

    def test_route_vision_uses_mock(self):
        # PURCHASE_AGREEMENT routes to VisionExtractor; mock the API.
        with _mock_anthropic('{"purchase_price": 612500}'):
            r = _run(route_extraction(b"%PDF-1.4 fake", "PURCHASE_AGREEMENT"))
        self.assertEqual(r.method, "claude_vision")
        self.assertEqual(r.fields["purchase_price"], 612500)


class VisionPromptTests(unittest.TestCase):
    def test_all_six_prompts_present(self):
        for dt in ("PURCHASE_AGREEMENT", "APPRAISAL_URAR", "GIFT_LETTER",
                   "VOE", "DIVORCE_DECREE", "SSA_AWARD_LETTER"):
            self.assertIn(dt, VisionExtractor.PROMPTS)
            self.assertTrue(VisionExtractor.PROMPTS[dt].strip())

    def test_parse_clean_json(self):
        self.assertEqual(VisionExtractor._parse_json('{"a": 1}'), {"a": 1})

    def test_parse_markdown_wrapped(self):
        self.assertEqual(
            VisionExtractor._parse_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_parse_prose_wrapped(self):
        self.assertEqual(
            VisionExtractor._parse_json('Here you go: {"a": 1} thanks'), {"a": 1})

    def test_parse_invalid_returns_none(self):
        self.assertIsNone(VisionExtractor._parse_json("not json at all"))

    def test_media_type_detection(self):
        self.assertEqual(VisionExtractor._media_type(b"%PDF-1.7"), "application/pdf")
        self.assertEqual(VisionExtractor._media_type(b"\xff\xd8\xff\xe0"), "image/jpeg")
        self.assertEqual(VisionExtractor._media_type(b"\x89PNG"), "image/png")


class VisionExtractTests(unittest.TestCase):
    def test_extract_parses_mocked_output(self):
        with _mock_anthropic('{"purchase_price": 612500, "close_date": "2026-08-15", "missing": null}'):
            r = _run(VisionExtractor().extract(b"%PDF-1.4", "PURCHASE_AGREEMENT"))
        self.assertEqual(r.method, "claude_vision")
        self.assertEqual(r.confidence, 0.85)
        self.assertEqual(r.fields["purchase_price"], 612500)
        self.assertNotIn("missing", r.fields)  # nulls dropped

    def test_extract_bad_json_flags_warning(self):
        with _mock_anthropic("sorry, I could not read it"):
            r = _run(VisionExtractor().extract(b"%PDF-1.4", "PURCHASE_AGREEMENT"))
        self.assertEqual(r.fields, {})
        self.assertTrue(r.warnings)

    def test_unknown_doc_type_returns_warning(self):
        r = _run(VisionExtractor().extract(b"x", "NOT_A_DOC_TYPE"))
        self.assertEqual(r.method, "vision_no_prompt")
        self.assertTrue(r.warnings)


class PipelineGuardTests(unittest.TestCase):
    def test_ingest_refuses_meridian(self):
        from core.extraction.pipeline import ingest_document
        with self.assertRaises(ValueError):
            _run(ingest_document(None, "APP-MRID-SC01", "meridian",
                                 "PURCHASE_AGREEMENT", b"x"))


class TextractExtractorTests(unittest.TestCase):
    """Tier 1 pdfplumber extractor. _extract_text is patched so no real PDF is
    needed — we test the FIELD_PATTERNS + parsing, not pdfplumber itself."""

    def _extract(self, text, doc_type):
        from core.extraction.textract_extractor import TextractExtractor
        with mock.patch.object(TextractExtractor, "_extract_text", return_value=text):
            return _run(TextractExtractor().extract(b"%PDF-fake", doc_type))

    def test_w2_fields(self):
        r = self._extract(
            "Employer ABC Corp EIN 12-3456789 Wages 102000.00 2024", "W2_CURRENT")
        self.assertEqual(r.method, "pdfplumber")
        self.assertEqual(r.fields["box1_wages"], 102000.00)
        self.assertEqual(r.fields["employer_name"], "ABC Corp")
        self.assertEqual(r.fields["employer_ein"], "12-3456789")
        self.assertEqual(r.fields["tax_year"], 2024.0)

    def test_paystub_fields(self):
        r = self._extract(
            "Gross Pay 4250.00 YTD 25500.00 Pay Date 06/15/2026", "PAYSTUB_CURRENT")
        self.assertEqual(r.fields["gross_pay_period"], 4250.00)
        self.assertEqual(r.fields["gross_pay_ytd"], 25500.00)
        self.assertEqual(r.fields["pay_date"], "06/15/2026")

    def test_urla_fields(self):
        r = self._extract("Loan Amount 400000 Property Type SFR", "URLA_1003")
        self.assertEqual(r.fields["loan_amount"], 400000.0)
        self.assertEqual(r.fields["property_type"], "SFR")

    def test_non_pdf_bytes_flags_error(self):
        from core.extraction.textract_extractor import TextractExtractor
        r = _run(TextractExtractor().extract(b"not a pdf", "W2_CURRENT"))
        self.assertEqual(r.method, "pdfplumber_error")
        self.assertEqual(r.fields, {})
        self.assertTrue(r.warnings)


class RegexExtractorTests(unittest.TestCase):
    """Tier 3 regex extractor over text bytes — no PDF, no mock needed."""

    def _extract(self, text, doc_type):
        from core.extraction.regex_extractor import RegexExtractor
        return _run(RegexExtractor().extract(text.encode("utf-8"), doc_type))

    def test_flood_cert(self):
        r = self._extract(
            "Flood Zone AE Community 120100 Effective 06/01/2026", "FLOOD_CERT")
        self.assertEqual(r.method, "regex")
        self.assertEqual(r.fields["flood_zone"], "AE")
        self.assertEqual(r.fields["community_number"], 120100.0)  # all-digits -> float
        self.assertEqual(r.fields["effective_date"], "06/01/2026")

    def test_hoi_binder(self):
        r = self._extract(
            "Dwelling Coverage 450000 Annual Premium 2400 Expiry 12/31/2026 "
            "Policy HO-12345678", "HOI_BINDER")
        self.assertEqual(r.fields["coverage_amount"], 450000.0)
        self.assertEqual(r.fields["annual_premium"], 2400.0)
        self.assertEqual(r.fields["policy_expiry"], "12/31/2026")
        self.assertEqual(r.fields["policy_number"], "HO-12345678")

    def test_rate_lock(self):
        r = self._extract(
            "Interest Rate 6.875 % Lock Expiry 07/15/2026 Loan Amount 400000",
            "RATE_LOCK")
        self.assertEqual(r.fields["interest_rate"], 6.875)
        self.assertEqual(r.fields["lock_expiry"], "07/15/2026")
        self.assertEqual(r.fields["loan_amount"], 400000.0)

    def test_credit_report(self):
        r = self._extract(
            "Equifax 720 Experian 715 TransUnion 725 "
            "Total Monthly Obligations 2300", "CREDIT_REPORT")
        self.assertEqual(r.fields["equifax_score"], 720.0)
        self.assertEqual(r.fields["experian_score"], 715.0)
        self.assertEqual(r.fields["transunion_score"], 725.0)
        self.assertEqual(r.fields["total_monthly_obligations"], 2300.0)

    def test_bank_statement(self):
        r = self._extract(
            "Ending Balance 45000.00 Statement Period Through 05/31/2026 "
            "Account ****1234", "BANK_STATEMENT_M1")
        self.assertEqual(r.fields["ending_balance"], 45000.00)
        self.assertEqual(r.fields["statement_date"], "05/31/2026")
        self.assertEqual(r.fields["account_number"], "****1234")

    def test_unknown_doc_type_warns(self):
        r = self._extract("anything", "NOT_A_TIER3_DOC")
        self.assertEqual(r.fields, {})
        self.assertTrue(r.warnings)


def _mock_anthropic(reply_text: str):
    """Patch anthropic.Anthropic so .messages.create returns a fake reply."""
    fake_block = types.SimpleNamespace(text=reply_text)
    fake_msg = types.SimpleNamespace(content=[fake_block])
    fake_client = mock.MagicMock()
    fake_client.messages.create.return_value = fake_msg
    return mock.patch("anthropic.Anthropic", return_value=fake_client)


if __name__ == "__main__":
    unittest.main()
