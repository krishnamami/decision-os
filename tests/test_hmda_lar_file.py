"""Unit tests for CF-A HMDA LAR file generator + CFPB edit checks (pure, no DB).

Synthetic hmda_lar records (the shape the table returns: action_taken/lien_status as
INTEGER codes, loan_type/purpose as text, action_taken_date as a date string) drive
the FIG pipe-delimited file builder and the S/V/Q/M edit engine. RULE 11: missing
required fields reported, never fabricated; submission_ready gated on error edits.
"""
import unittest

from core.compliance.hmda_lar_file import (
    LAR_FIELD_ORDER,
    generate_lar_file,
    generate_lar_row,
    parse_lar_rows,
)
from core.compliance.hmda_edit_checks import run_edit_checks

META = {"tenant_id": "meridian", "lei": "0" * 20,
        "institution_name": "Meridian Bank", "contact_email": "uw@meridian.com"}

GOOD = {"application_id": "APP-1", "action_taken": 1, "action_taken_date": "2024-03-15",
        "loan_type": "conventional", "loan_purpose": "purchase", "loan_amount": 400000,
        "occupancy_type": "primary", "lien_status": 1, "state_code": "06",
        "county_code": "06037", "census_tract": "06037123456",
        "applicant_ethnicity": 2, "applicant_race": 5, "applicant_sex": 1,
        "applicant_income": 96000, "interest_rate": 6.5}

MERIDIAN_LIKE = {"application_id": "APP-MRID-SC16", "action_taken": 1,
                 "action_taken_date": "2026-06-23", "loan_type": "other",
                 "loan_purpose": None, "loan_amount": 374000, "occupancy_type": None,
                 "lien_status": 1, "applicant_ethnicity": 3, "applicant_race": 6,
                 "applicant_sex": 3, "applicant_income": 96000}

DENIED_NO_REASON = {"application_id": "APP-D", "action_taken": 3,
                    "action_taken_date": "2024-05-01", "loan_type": "fha",
                    "loan_purpose": "purchase", "loan_amount": 300000,
                    "occupancy_type": "primary", "lien_status": 1, "census_tract": "x",
                    "applicant_ethnicity": 1, "denial_reasons": []}


def _row_dict(record):
    line, missing = generate_lar_row(record, META)
    vals = line.split("|")
    return dict(zip(LAR_FIELD_ORDER, vals)), missing


class LarRowTests(unittest.TestCase):
    def test_field_count_matches_order(self):
        line, _ = generate_lar_row(GOOD, META)
        self.assertEqual(len(line.split("|")), len(LAR_FIELD_ORDER))

    def test_loan_type_mapped(self):
        d, _ = _row_dict(GOOD)
        self.assertEqual(d["loan_type"], "1")          # conventional -> 1
        self.assertEqual(d["record_identifier"], "2")

    def test_loan_type_other_blank_and_missing(self):
        d, missing = _row_dict(MERIDIAN_LIKE)
        self.assertEqual(d["loan_type"], "")           # 'other' -> invalid -> blank
        self.assertIn("loan_type", missing)
        self.assertIn("loan_purpose", missing)         # None -> missing

    def test_action_taken_integer_code_passthrough(self):
        d, _ = _row_dict(GOOD)
        self.assertEqual(d["action_taken"], "1")       # int 1 emitted directly

    def test_lien_status_integer_passthrough(self):
        d, _ = _row_dict(GOOD)
        self.assertEqual(d["lien_status"], "1")

    def test_date_formatted_yyyymmdd(self):
        d, _ = _row_dict(GOOD)
        self.assertEqual(d["action_taken_date"], "20240315")  # dashes stripped

    def test_loan_purpose_cashout_code(self):
        d, _ = _row_dict({**GOOD, "loan_purpose": "cash_out_refinance"})
        self.assertEqual(d["loan_purpose"], "32")

    def test_uli_synthesized(self):
        d, _ = _row_dict(GOOD)
        self.assertTrue(d["uli"].endswith("APP-1"))


class LarFileTests(unittest.TestCase):
    def test_transmittal_first_line(self):
        text, _ = generate_lar_file([GOOD, MERIDIAN_LIKE], META, 2024)
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("1|"))
        self.assertEqual(len(lines), 3)               # TS + 2 LAR
        self.assertTrue(all(l.startswith("2|") for l in lines[1:]))

    def test_missing_report(self):
        _, missing = generate_lar_file([GOOD, MERIDIAN_LIKE], META, 2024)
        apps = {m["application_id"] for m in missing}
        self.assertIn("APP-MRID-SC16", apps)          # has missing fields
        self.assertNotIn("APP-1", apps)               # GOOD is complete

    def test_parse_round_trip(self):
        text, _ = generate_lar_file([GOOD], META, 2024)
        rows = parse_lar_rows(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["loan_amount"], "400000")


class EditCheckTests(unittest.TestCase):
    def _check(self, records):
        text, _ = generate_lar_file(records, META, 2024)
        return run_edit_checks(records, parse_lar_rows(text))

    def _ids(self, report, key):
        return {r["id"] for r in report[key]}

    def test_good_record_submission_ready(self):
        rep = self._check([GOOD])
        self.assertTrue(rep["submission_ready"], rep["errors"])
        self.assertEqual(rep["error_count"], 0)

    def test_meridian_loan_type_flags_v210(self):
        rep = self._check([MERIDIAN_LIKE])
        self.assertFalse(rep["submission_ready"])
        self.assertIn("V210", self._ids(rep, "errors"))   # loan_type 'other'
        self.assertIn("V225", self._ids(rep, "errors"))   # loan_purpose missing

    def test_denied_without_reason_flags_v350(self):
        rep = self._check([DENIED_NO_REASON])
        self.assertIn("V350", self._ids(rep, "errors"))

    def test_bad_lei_flags_s010(self):
        rep = run_edit_checks([GOOD], parse_lar_rows(
            generate_lar_file([GOOD], {**META, "lei": "SHORT"}, 2024)[0]))
        self.assertIn("S010", self._ids(rep, "errors"))

    def test_quality_loan_amount_warning(self):
        rep = self._check([{**GOOD, "loan_amount": 15_000_000}])
        self.assertIn("Q614", self._ids(rep, "warnings"))
        self.assertTrue(rep["submission_ready"])          # warning doesn't block

    def test_macro_denial_rate(self):
        rep = self._check([DENIED_NO_REASON, {**DENIED_NO_REASON, "application_id": "APP-D2",
                                              "denial_reasons": [1]}])
        self.assertIn("M001", self._ids(rep, "infos"))    # 100% denial rate

    def test_rule11_provenance(self):
        rep = self._check([MERIDIAN_LIKE])
        self.assertIn("data_source", rep)
        self.assertIn("missing_inputs", rep)
        self.assertTrue(rep["missing_inputs"])            # errors present


if __name__ == "__main__":
    unittest.main()
