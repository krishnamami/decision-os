"""Unit tests for PL-E ProductMatrixExtractor (pure, no DB, no API key, stdlib csv).

Synthetic product-matrix CSV fixtures exercise the clean parse, the messy-header
normalization, value coercion ($/%/empty), loan_type/purpose/is_active
normalization, derived product_id, the draft proposal shape, and RULE 11
provenance (confidence + source_row + warnings + missing_inputs + unmapped_items).
"""
import unittest

from core.extraction.product_matrix_extractor import ProductMatrixExtractor

PRODUCT_CSV = """
product_id,product_name,loan_type,loan_purpose,min_credit_score,max_dti,max_ltv,max_loan_amount,is_active
CONV-30,Conventional 30yr Fixed,conventional,purchase,660,43,95,806500,YES
FHA-30,FHA 30yr Fixed,fha,all,580,50,96.5,498257,YES
VA-30,VA 30yr Fixed,va,purchase,620,41,100,,NO
JUMBO,Jumbo Fixed,jumbo,purchase,720,43,80,3000000,YES
HOMEREADY,HomeReady,conventional,purchase,620,45,97,806500,YES
"""

MESSY_CSV = """
Product Name,Min FICO,Max Debt Ratio,LTV Max,Max Loan,Offered
Conv 30 Fixed,660,43%,95%,$806500,YES
FHA 30,580,50%,96.5%,$498257,YES
VA - Not Offered,620,41%,100%,N/A,NO
"""


class CleanParseTests(unittest.TestCase):
    def setUp(self):
        self.r = ProductMatrixExtractor()
        self.rows, self.unmapped, self.missing = self.r.parse(PRODUCT_CSV)

    def test_row_count(self):
        self.assertEqual(len(self.rows), 5)
        self.assertEqual(self.missing, [])

    def test_first_product(self):
        p = self.rows[0]
        self.assertEqual(p.product_id, "CONV-30")
        self.assertEqual(p.product_name, "Conventional 30yr Fixed")
        self.assertEqual(p.loan_type, "conventional")
        self.assertEqual(p.min_credit_score, 660)
        self.assertEqual(p.max_dti, 43.0)
        self.assertEqual(p.max_ltv, 95.0)
        self.assertEqual(p.max_loan_amount, 806500)
        self.assertTrue(p.is_active)

    def test_is_active_no(self):
        va = [p for p in self.rows if p.product_id == "VA-30"][0]
        self.assertFalse(va.is_active)

    def test_va_empty_max_loan_is_none_not_crash(self):
        va = [p for p in self.rows if p.product_id == "VA-30"][0]
        self.assertIsNone(va.max_loan_amount)
        self.assertEqual(va.max_ltv, 100.0)

    def test_decimal_ltv(self):
        fha = [p for p in self.rows if p.product_id == "FHA-30"][0]
        self.assertEqual(fha.max_ltv, 96.5)

    def test_confidence_full_row(self):
        # CONV-30 has score/dti/ltv all present → top confidence, no warnings
        p = self.rows[0]
        self.assertEqual(p.confidence, 0.95)
        self.assertEqual(p.warnings, [])


class MessyHeaderTests(unittest.TestCase):
    def setUp(self):
        self.r = ProductMatrixExtractor()
        self.rows, self.unmapped, self.missing = self.r.parse(MESSY_CSV)

    def test_three_products_despite_messy_headers(self):
        self.assertEqual(len(self.rows), 3)

    def test_headers_normalized(self):
        p = self.rows[0]
        self.assertEqual(p.product_name, "Conv 30 Fixed")
        self.assertEqual(p.min_credit_score, 660)   # "Min FICO"
        self.assertEqual(p.max_ltv, 95.0)           # "LTV Max"
        self.assertEqual(p.max_loan_amount, 806500)  # "$806500" → "Max Loan"
        self.assertEqual(p.max_dti, 43.0)            # "Max Debt Ratio" synonym

    def test_pct_and_dollar_coercion(self):
        p = self.rows[0]
        self.assertEqual(p.max_dti, 43.0)   # from "43%"
        self.assertEqual(p.max_loan_amount, 806500)  # from "$806500"

    def test_no_loan_type_column_defaults_conventional(self):
        # MESSY_CSV has no loan_type column
        self.assertTrue(all(p.loan_type == "conventional" for p in self.rows))

    def test_derived_product_id_when_absent(self):
        # no product_id column → derived from name + loan_type
        for p in self.rows:
            self.assertTrue(p.product_id)
            self.assertNotIn(" ", p.product_id)

    def test_offered_no_parsed_false(self):
        va = [p for p in self.rows if "Not Offered" in p.product_name][0]
        self.assertFalse(va.is_active)
        self.assertIsNone(va.max_loan_amount)  # "N/A" → None


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        self.r = ProductMatrixExtractor()

    def test_loan_type_map(self):
        self.assertEqual(self.r._normalize_loan_type("Conv"), "conventional")
        self.assertEqual(self.r._normalize_loan_type("FHA"), "fha")
        self.assertEqual(self.r._normalize_loan_type(""), "conventional")
        self.assertEqual(self.r._normalize_loan_type("portfolio"), "portfolio")

    def test_loan_purpose_map(self):
        self.assertEqual(self.r._normalize_loan_purpose("Cash Out Refi"), "cash_out_refi")
        self.assertEqual(self.r._normalize_loan_purpose("Rate/Term"), "rate_term_refi")
        self.assertEqual(self.r._normalize_loan_purpose("Purchase"), "purchase")
        self.assertEqual(self.r._normalize_loan_purpose("anything"), "all")

    def test_amount_and_pct(self):
        self.assertEqual(self.r._parse_amount("$806,500"), 806500)
        self.assertIsNone(self.r._parse_amount(""))
        self.assertIsNone(self.r._parse_amount("N/A"))
        self.assertEqual(self.r._parse_pct("43%"), 43.0)

    def test_bool(self):
        self.assertTrue(self.r._parse_bool("YES"))
        self.assertTrue(self.r._parse_bool("true"))
        self.assertTrue(self.r._parse_bool("1"))
        self.assertFalse(self.r._parse_bool("NO"))
        self.assertFalse(self.r._parse_bool(""))


class DegradeAndProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.r = ProductMatrixExtractor()

    def test_empty_csv(self):
        _, _, missing = self.r.parse("")
        self.assertTrue(missing)

    def test_no_recognized_headers(self):
        _, _, missing = self.r.parse("foo,bar,baz\n1,2,3\n")
        self.assertTrue(any("recognized" in m for m in missing))

    def test_unmapped_column_surfaced(self):
        csv = ("product_name,min_credit_score,exotic_column\n"
               "Conv 30,660,whatever\n")
        rows, unmapped, _ = self.r.parse(csv)
        self.assertEqual(len(rows), 1)
        self.assertTrue(any(u.get("header") == "exotic_column" for u in unmapped))

    def test_warnings_lower_confidence(self):
        csv = "product_name,loan_type\nConv 30,conventional\n"  # no score/dti/ltv
        rows, _, _ = self.r.parse(csv)
        self.assertEqual(len(rows[0].warnings), 3)
        self.assertEqual(rows[0].confidence, 0.65)

    def test_empty_product_name_row_unmapped(self):
        csv = "product_id,product_name,loan_type\nX,,conventional\nY,Real,fha\n"
        rows, unmapped, _ = self.r.parse(csv)
        self.assertEqual(len(rows), 1)
        self.assertTrue(any(u.get("reason") == "empty product_name" for u in unmapped))


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.r = ProductMatrixExtractor()

    def test_draft_shape(self):
        out = self.r.extract(PRODUCT_CSV.encode(), "products.csv", "meridian")
        self.assertEqual(out["status"], "draft")
        self.assertEqual(out["row_count"], 5)
        self.assertGreater(out["avg_confidence"], 0.8)
        self.assertIn("REVIEW REQUIRED", out["note"])
        self.assertIn("activate", out["next_steps"])

    def test_product_rows_are_dicts(self):
        out = self.r.extract(PRODUCT_CSV.encode(), "products.csv")
        self.assertIsInstance(out["product_rows"][0], dict)
        self.assertEqual(out["product_rows"][0]["product_id"], "CONV-30")

    def test_rule11_provenance(self):
        out = self.r.extract(PRODUCT_CSV.encode(), "products.csv")
        self.assertIn("data_source", out)
        self.assertIn("missing_inputs", out)
        self.assertIsInstance(out["unmapped_items"], list)
        for p in out["product_rows"]:
            self.assertIn("confidence", p)
            self.assertIn("source_row", p)
            self.assertIn("warnings", p)

    def test_empty_file_surfaces_missing(self):
        out = self.r.extract(b"", "empty.csv")
        self.assertEqual(out["row_count"], 0)
        self.assertTrue(out["missing_inputs"])


if __name__ == "__main__":
    unittest.main()
