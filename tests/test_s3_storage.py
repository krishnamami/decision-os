"""Unit tests for the RA-P0-A MISMO S3 storage layer (key builder + client)."""
import asyncio
import unittest

from core.storage import s3_keys
from core.storage.s3_client import S3Client


def _run(coro):
    return asyncio.run(coro)


class KeyFormatTests(unittest.TestCase):
    def test_doc_raw_key(self):
        k = s3_keys.doc_raw_key("acme", "APP1", "W2_CURRENT", "w2.pdf")
        self.assertEqual(k, "acme/APP1/uploads/raw/W2_CURRENT/w2.pdf")

    def test_doc_processed_key(self):
        k = s3_keys.doc_processed_key("acme", "APP1", "W2_CURRENT")
        self.assertEqual(k, "acme/APP1/uploads/processed/W2_CURRENT.json")

    def test_mismo_raw_key_includes_version(self):
        self.assertEqual(s3_keys.mismo_raw_key("acme", "APP1"),
                         "acme/APP1/mismo/raw/3x.xml")
        self.assertEqual(s3_keys.mismo_raw_key("acme", "APP1", "3.4"),
                         "acme/APP1/mismo/raw/3.4.xml")

    def test_mismo_parsed_key(self):
        self.assertEqual(s3_keys.mismo_parsed_key("acme", "APP1"),
                         "acme/APP1/mismo/parsed/canonical.json")

    def test_aus_du_key_includes_casefile(self):
        self.assertEqual(s3_keys.aus_du_key("acme", "APP1", "DU123"),
                         "acme/APP1/aus/du/DU123.json")

    def test_aus_lp_key_includes_key_number(self):
        self.assertEqual(s3_keys.aus_lp_key("acme", "APP1", "LP999"),
                         "acme/APP1/aus/lp/LP999.json")

    def test_platform_onboarding_key(self):
        self.assertEqual(s3_keys.platform_onboarding_key("acme", "policy.pdf"),
                         "acme/platform/onboarding/policy.pdf")

    def test_hmda_export_key_year_month_padded(self):
        self.assertEqual(s3_keys.hmda_export_key("acme", 2026, 3),
                         "acme/exports/hmda/2026/03/lar.csv")
        self.assertEqual(s3_keys.hmda_export_key("acme", 2026, 12),
                         "acme/exports/hmda/2026/12/lar.csv")

    def test_dmn_export_key(self):
        self.assertEqual(s3_keys.dmn_export_key("acme", "v1"),
                         "acme/exports/dmn/v1/rules.xml")


class KeyHygieneTests(unittest.TestCase):
    """Every key: tenant-isolated, no leading slash, no double slash."""

    def _all_keys(self):
        return [
            s3_keys.doc_raw_key("acme", "APP1", "W2", "f.pdf"),
            s3_keys.doc_processed_key("acme", "APP1", "W2"),
            s3_keys.mismo_raw_key("acme", "APP1"),
            s3_keys.mismo_parsed_key("acme", "APP1"),
            s3_keys.aus_du_key("acme", "APP1", "DU1"),
            s3_keys.aus_lp_key("acme", "APP1", "LP1"),
            s3_keys.platform_onboarding_key("acme", "f.pdf"),
            s3_keys.hmda_export_key("acme", 2026, 1),
            s3_keys.dmn_export_key("acme", "v1"),
        ]

    def test_no_leading_or_double_slash(self):
        for k in self._all_keys():
            self.assertFalse(k.startswith("/"), k)
            self.assertNotIn("//", k)
            self.assertTrue(k.startswith("acme/"), f"not tenant-isolated: {k}")

    def test_stray_slashes_are_stripped(self):
        # Messy inputs must still yield a clean key.
        k = s3_keys.doc_raw_key("/acme/", "/APP1/", "/W2/", "f.pdf")
        self.assertEqual(k, "acme/APP1/uploads/raw/W2/f.pdf")
        self.assertNotIn("//", k)
        self.assertFalse(k.startswith("/"))


class S3ClientFallbackTests(unittest.TestCase):
    """With no AWS credentials, every operation degrades gracefully."""

    def setUp(self):
        # Force the no-credentials path regardless of the host environment.
        self.client = S3Client()
        self.client._resolved = True
        self.client._client = None

    def test_put_returns_false_without_credentials(self):
        self.assertFalse(_run(self.client.put("acme/APP1/x", b"data")))

    def test_get_returns_none_without_credentials(self):
        self.assertIsNone(_run(self.client.get("acme/APP1/x")))

    def test_exists_returns_false_without_credentials(self):
        self.assertFalse(_run(self.client.exists("acme/APP1/x")))

    def test_default_bucket(self):
        self.assertEqual(S3Client()._bucket, "accord-docs")


if __name__ == "__main__":
    unittest.main()
