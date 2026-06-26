"""Unit tests for PL-D RateSheetExtractor (pure, no DB, no API key, stdlib csv).

Synthetic rate-sheet CSV fixtures exercise the FICO×LTV grid parse, the
purpose/property/occupancy adjustment blocks, the rate_sheet_entry base-rate
parse (exact rate_sheet_upload columns), the draft proposal shape, and RULE 11
provenance (confidence + source_row + missing_inputs + unmapped_items). The
fixtures carry leading/trailing blank lines on purpose — real lender exports do.
"""
import unittest

from core.extraction.rate_sheet_extractor import RateSheetExtractor

GRID_CSV = """
,≤60,≤65,≤70,≤75,≤80,≤85,≤90,≤95,≤97
620-639,3.000,3.000,3.000,3.000,3.000,3.500,3.500,3.500,3.500
640-659,2.250,2.250,2.250,2.250,2.250,2.750,2.750,3.000,3.000
660-679,1.750,1.750,1.750,1.750,1.750,2.250,2.500,2.750,2.750
680-699,1.500,1.500,1.500,1.500,1.500,1.750,2.000,2.250,2.250
700-719,1.250,1.250,1.250,1.250,1.250,1.500,1.750,2.000,2.000
720-739,0.500,0.500,0.500,0.500,0.500,0.750,1.000,1.500,1.500
740-759,0.250,0.250,0.250,0.250,0.250,0.250,0.250,0.500,0.750
760-779,0.000,0.000,0.000,0.000,0.000,0.000,0.000,0.125,0.250
780+,-0.250,-0.250,-0.250,-0.250,-0.375,-0.375,-0.375,-0.375,-0.375
"""

PURPOSE_CSV = """
purchase,0.000
rate_term_refi,0.250
cash_out_refi,0.375
"""

OCCUPANCY_CSV = """
primary,0.000
second home,0.250
investment,0.750
"""

RATE_SHEET_CSV = """
product_id,credit_band,ltv_max,base_rate,llpa_adjustment,effective_date
CONV_30,720-739,80,6.750,0.250,2025-01-01
CONV_30,740-759,80,6.750,0.000,2025-01-01
CONV_30,760+,80,6.750,-0.125,2025-01-01
FHA_30,620-639,96.5,7.250,0.500,2025-01-01
"""


class GridTests(unittest.TestCase):
    def setUp(self):
        self.r = RateSheetExtractor()
        self.rows, self.unmapped, self.missing = self.r.parse_fico_ltv_grid(GRID_CSV)

    def test_full_grid_row_count(self):
        self.assertEqual(len(self.rows), 81)  # 9 FICO bands × 9 LTV cols
        self.assertEqual(self.missing, [])

    def test_first_cell(self):
        first = self.rows[0]
        self.assertEqual(first.credit_score_min, 620)
        self.assertEqual(first.credit_score_max, 639)
        self.assertEqual(first.ltv_max, 60.0)
        self.assertEqual(first.adjustment_pct, 3.000)
        self.assertEqual(first.adjustment_type, "credit_score_ltv")

    def test_open_top_band(self):
        # 780+ → 780..850
        top = [r for r in self.rows if r.credit_score_min == 780]
        self.assertTrue(top)
        self.assertEqual(top[0].credit_score_max, 850)

    def test_high_ltv_column(self):
        self.assertTrue(any(r.ltv_max == 97.0 for r in self.rows))

    def test_negative_adjustment_preserved(self):
        # 780+ / ≤80 = -0.375
        neg = [r for r in self.rows if r.credit_score_min == 780 and r.ltv_max == 80.0]
        self.assertEqual(neg[0].adjustment_pct, -0.375)

    def test_score_band_parser(self):
        self.assertEqual(self.r._parse_score_band("720-739"), (720, 739))
        self.assertEqual(self.r._parse_score_band(">=780"), (780, 850))
        self.assertEqual(self.r._parse_score_band("<620"), (300, 620))
        self.assertEqual(self.r._parse_score_band("780+"), (780, 850))
        self.assertEqual(self.r._parse_score_band("garbage"), (None, None))

    def test_unrecognized_band_unmapped_not_dropped(self):
        bad = "\n,≤80\nNOTABAND,0.5\n720-739,0.25\n"
        rows, unmapped, _ = self.r.parse_fico_ltv_grid(bad)
        self.assertEqual(len(rows), 1)  # only the valid band
        self.assertTrue(any(u.get("band") == "NOTABAND" for u in unmapped))

    def test_insufficient_rows(self):
        rows, _, missing = self.r.parse_fico_ltv_grid("\n,≤80\n")
        self.assertEqual(rows, [])
        self.assertTrue(missing)


class AdjustmentBlockTests(unittest.TestCase):
    def setUp(self):
        self.r = RateSheetExtractor()

    def test_purpose(self):
        rows, unmapped = self.r.parse_purpose_adjustments(PURPOSE_CSV)
        m = {x["loan_purpose"]: x["adjustment_pct"] for x in rows}
        self.assertEqual(m["purchase"], 0.000)
        self.assertEqual(m["rate_term_refi"], 0.250)
        self.assertEqual(m["cash_out_refi"], 0.375)
        self.assertEqual(unmapped, [])

    def test_occupancy_normalization(self):
        rows, _ = self.r.parse_occupancy_adjustments(OCCUPANCY_CSV)
        m = {x["occupancy_type"]: x["adjustment_pct"] for x in rows}
        self.assertEqual(m["primary"], 0.000)
        self.assertEqual(m["second_home"], 0.250)
        self.assertEqual(m["investment"], 0.750)

    def test_property_normalization(self):
        rows, _ = self.r.parse_property_adjustments("condo,0.75\nSFR,0.0\n2-4 unit,1.0\n")
        m = {x["property_type"]: x["adjustment_pct"] for x in rows}
        self.assertEqual(m["condo"], 0.75)
        self.assertEqual(m["single_family"], 0.0)  # "SFR" → single_family
        self.assertEqual(m["multi_unit"], 1.0)     # "2-4 unit" → multi_unit

    def test_property_unknown_defaults_single_family(self):
        rows, _ = self.r.parse_property_adjustments("weird,0.1\n")
        self.assertEqual(rows[0]["property_type"], "single_family")

    def test_non_numeric_adj_unmapped(self):
        rows, unmapped = self.r.parse_purpose_adjustments("purchase,N/A\nrefi,0.25\n")
        self.assertEqual(len(rows), 1)
        self.assertTrue(unmapped)


class RateSheetEntryTests(unittest.TestCase):
    def setUp(self):
        self.r = RateSheetExtractor()

    def test_parse_rows(self):
        rows, unmapped, missing = self.r.parse_rate_sheet_entry(RATE_SHEET_CSV)
        self.assertEqual(len(rows), 4)
        self.assertEqual(missing, [])
        self.assertEqual(rows[0].product_id, "CONV_30")
        self.assertEqual(rows[0].ltv_max, 80.0)
        self.assertEqual(rows[0].base_rate, 6.750)
        self.assertEqual(rows[0].llpa_adjustment, 0.250)
        self.assertEqual(rows[3].ltv_max, 96.5)
        self.assertEqual(rows[2].llpa_adjustment, -0.125)

    def test_missing_required_columns(self):
        rows, _, missing = self.r.parse_rate_sheet_entry(
            "product_id,base_rate\nCONV_30,6.75\n")
        self.assertEqual(rows, [])
        self.assertTrue(any("Missing required columns" in m for m in missing))

    def test_bad_row_unmapped_not_dropped(self):
        bad = ("product_id,credit_band,ltv_max,base_rate,llpa_adjustment,effective_date\n"
               "CONV_30,720-739,NOTANUM,6.75,0.25,2025-01-01\n"
               "CONV_30,740-759,80,6.75,0.0,2025-01-01\n")
        rows, unmapped, _ = self.r.parse_rate_sheet_entry(bad)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(unmapped), 1)


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.r = RateSheetExtractor()

    def test_both_shapes(self):
        out = self.r.extract(
            RATE_SHEET_CSV.encode(), "rates.csv",
            sheet_hints={"rate_sheet": RATE_SHEET_CSV, "grid": GRID_CSV,
                         "purpose": PURPOSE_CSV})
        self.assertEqual(out["rs_row_count"], 4)
        self.assertEqual(out["llpa_row_count"], 81 + 3)  # grid + 3 purpose
        self.assertGreater(out["avg_confidence"], 0.8)

    def test_draft_never_activates(self):
        out = self.r.extract(RATE_SHEET_CSV.encode(), "rates.csv")
        self.assertEqual(out["status"], "draft")
        self.assertIn("REVIEW REQUIRED", out["note"])
        self.assertIn("base_rates", out["next_steps"])
        self.assertIn("llpa_grid", out["next_steps"])

    def test_whole_file_as_rate_sheet(self):
        # no sheet_hints → entire file treated as a rate_sheet_entry CSV
        out = self.r.extract(RATE_SHEET_CSV.encode(), "rates.csv")
        self.assertEqual(out["rs_row_count"], 4)
        self.assertEqual(out["llpa_row_count"], 0)

    def test_rows_are_jsonable_dicts(self):
        out = self.r.extract(RATE_SHEET_CSV.encode(), "rates.csv",
                             sheet_hints={"grid": GRID_CSV})
        self.assertIsInstance(out["llpa_rows"][0], dict)
        self.assertIn("source_row", out["llpa_rows"][0])
        self.assertIn("confidence", out["llpa_rows"][0])

    def test_empty_file_surfaces_missing(self):
        out = self.r.extract(b"", "empty.csv")
        self.assertEqual(out["rs_row_count"], 0)
        self.assertTrue(out["missing_inputs"])


class Rule11Tests(unittest.TestCase):
    def test_provenance(self):
        out = RateSheetExtractor().extract(
            RATE_SHEET_CSV.encode(), "rates.csv", sheet_hints={"grid": GRID_CSV})
        self.assertIn("data_source", out)
        self.assertIn("missing_inputs", out)
        self.assertIsInstance(out["unmapped_items"], list)
        for r in out["rate_sheet_entry_rows"] + out["llpa_rows"]:
            self.assertIn("confidence", r)
            self.assertIn("source_row", r)


if __name__ == "__main__":
    unittest.main()
