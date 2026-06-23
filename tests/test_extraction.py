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

    def test_route_textract_is_stub(self):
        r = _run(route_extraction(b"x", "W2_CURRENT"))
        self.assertEqual(r.method, "textract_stub")

    def test_route_regex_is_stub(self):
        r = _run(route_extraction(b"x", "FLOOD_CERT"))
        self.assertEqual(r.method, "regex_stub")

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


def _mock_anthropic(reply_text: str):
    """Patch anthropic.Anthropic so .messages.create returns a fake reply."""
    fake_block = types.SimpleNamespace(text=reply_text)
    fake_msg = types.SimpleNamespace(content=[fake_block])
    fake_client = mock.MagicMock()
    fake_client.messages.create.return_value = fake_msg
    return mock.patch("anthropic.Anthropic", return_value=fake_client)


if __name__ == "__main__":
    unittest.main()
