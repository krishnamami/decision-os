"""Unit tests for the EV-H field manifest + verifier (pure, no DB).

Honest per-app semantics: `assumed` = field NULL *and* a consumer defaults it;
`missing` = NULL with no defaulter; `present` otherwise. The three silent-default
fields are also surfaced statically (fields_with_silent_default_risk).
"""
import unittest

from core.evidence.field_manifest import (
    FIELD_MANIFEST,
    FIELDS_WITH_SILENT_DEFAULTS,
    MANIFEST_BY_FIELD,
    REQUIRED_FIELDS,
)
from core.evidence.field_manifest_verifier import FieldManifestVerifier


def _full_row(**over):
    row = {
        "mid_credit_score": 720, "ltv": 90.0, "dti_back": 42.0,
        "qualifying_monthly": 8000.0, "total_liquid_assets": 24500.0,
        "piti_monthly": 2678.5, "loan_amount": 382500.0,
        "appraised_value": 416000.0, "monthly_obligations": 1800.0,
        "loan_terms": {"loan_type": "conventional"},
    }
    row.update(over)
    return row


class ManifestTests(unittest.TestCase):
    def test_ten_entries_all_have_consumers_and_required_for(self):
        self.assertEqual(len(FIELD_MANIFEST), 10)
        self.assertEqual(len(MANIFEST_BY_FIELD), 10)
        for f in FIELD_MANIFEST:
            self.assertTrue(f.consumers, f.field_name)
            if f.required:
                self.assertTrue(f.required_for, f.field_name)

    def test_three_silent_default_fields(self):
        names = {f.field_name for f in FIELDS_WITH_SILENT_DEFAULTS}
        self.assertEqual(names, {"mid_credit_score", "ltv", "dti_back"})

    def test_all_required(self):
        self.assertEqual(len(REQUIRED_FIELDS), 10)


class VerifyFieldTests(unittest.TestCase):
    def setUp(self):
        self.v = FieldManifestVerifier()

    def test_present_field(self):
        r = self.v.verify_field(MANIFEST_BY_FIELD["mid_credit_score"], _full_row())
        self.assertEqual(r["status"], "present")
        self.assertEqual(r["value"], 720)
        self.assertEqual(r["missing_inputs"], [])
        self.assertIsNone(r["broken_hop"])

    def test_null_with_silent_default_is_assumed(self):
        r = self.v.verify_field(MANIFEST_BY_FIELD["dti_back"], _full_row(dti_back=None))
        self.assertEqual(r["status"], "assumed")
        self.assertTrue(r["missing_inputs"])
        self.assertIn("rate_pricing", r["missing_inputs"][0])
        self.assertIsNotNone(r["broken_hop"])

    def test_null_without_default_is_missing(self):
        r = self.v.verify_field(MANIFEST_BY_FIELD["qualifying_monthly"],
                                _full_row(qualifying_monthly=None))
        self.assertEqual(r["status"], "missing")
        self.assertTrue(r["missing_inputs"])

    def test_jsonb_loan_type_present(self):
        r = self.v.verify_field(MANIFEST_BY_FIELD["loan_type"], _full_row())
        self.assertEqual(r["status"], "present")
        self.assertEqual(r["value"], "conventional")

    def test_jsonb_loan_type_missing_when_key_absent(self):
        # the loan_terms dict exists but has no loan_type key -> must NOT count present
        r = self.v.verify_field(MANIFEST_BY_FIELD["loan_type"],
                                _full_row(loan_terms={"other": 1}))
        self.assertEqual(r["status"], "missing")

    def test_jsonb_string_column_parsed(self):
        r = self.v.verify_field(MANIFEST_BY_FIELD["loan_type"],
                                _full_row(loan_terms='{"loan_type": "fha"}'))
        self.assertEqual(r["status"], "present")
        self.assertEqual(r["value"], "fha")


class VerifyAllTests(unittest.TestCase):
    def setUp(self):
        self.v = FieldManifestVerifier()

    def test_all_present(self):
        r = self.v.verify_all(_full_row())
        self.assertEqual(r["present_count"], 10)
        self.assertEqual(r["assumed_count"], 0)
        self.assertEqual(r["missing_count"], 0)
        self.assertEqual(r["completeness_pct"], 100.0)
        self.assertIsNone(r["silent_default_warning"])
        self.assertEqual(set(r["fields_with_silent_default_risk"]),
                         {"mid_credit_score", "ltv", "dti_back"})

    def test_sc03_dti_assumed(self):
        r = self.v.verify_all(_full_row(dti_back=None))
        self.assertEqual(r["assumed_count"], 1)
        self.assertIn("dti_back", r["assumed_fields"])
        self.assertEqual(r["completeness_pct"], 90.0)
        self.assertIsNotNone(r["silent_default_warning"])
        dc = r["decision_completeness"]
        self.assertFalse(dc["dti_calculation"]["complete"])
        self.assertIn("dti_back", dc["dti_calculation"]["gap_fields"])
        self.assertTrue(dc["dti_calculation"]["ran_on_assumed"])

    def test_true_missing_field(self):
        r = self.v.verify_all(_full_row(qualifying_monthly=None))
        self.assertIn("qualifying_monthly", r["missing_fields"])
        self.assertEqual(r["assumed_count"], 0)

    def test_rule11_provenance_on_every_result(self):
        r = self.v.verify_all(_full_row(dti_back=None))
        for res in r["results"]:
            self.assertIn("data_source", res)
            self.assertIn("missing_inputs", res)
        self.assertTrue(r["missing_inputs"])  # SC03 dti surfaced at top level


if __name__ == "__main__":
    unittest.main()
