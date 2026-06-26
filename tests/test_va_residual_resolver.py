"""Unit tests for FR-F VAResidualIncomeResolver (pure, no DB).

Synthetic VA loans across regions/family sizes exercise the residual math, the
VA Pamphlet 26-7 table accuracy, the per-additional-person extension, and the
not_applicable / missing_inputs guards. RULE 11 provenance asserted.
"""
import unittest

from core.compliance.va_residual_resolver import (
    REGION_BY_STATE,
    VA_RESIDUAL_TABLE,
    VAResidualIncomeResolver,
)


def _va(**over):
    base = {"loan_type": "va", "qualifying_monthly": 8000, "piti_monthly": 2000,
            "monthly_obligations": 500, "property_state": "CA", "family_size": 3,
            "gross_living_area": 1500, "loan_amount": 400000}
    base.update(over)
    return base


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.r = VAResidualIncomeResolver()

    def test_non_va_not_applicable(self):
        out = self.r.qualify_va_residual(_va(loan_type="conventional"))
        self.assertEqual(out["status"], "not_applicable")

    def test_missing_family_size(self):
        out = self.r.qualify_va_residual(_va(family_size=None))
        self.assertEqual(out["status"], "not_applicable")
        self.assertTrue(any("family_size" in m for m in out["missing_inputs"]))

    def test_missing_income(self):
        out = self.r.qualify_va_residual(_va(qualifying_monthly=0))
        self.assertEqual(out["status"], "not_applicable")

    def test_unmapped_state(self):
        out = self.r.qualify_va_residual(_va(property_state="ZZ"))
        self.assertEqual(out["status"], "not_applicable")
        self.assertTrue(any("region" in m for m in out["missing_inputs"]))

    def test_small_loan_not_applicable(self):
        out = self.r.qualify_va_residual(_va(loan_amount=50000))
        self.assertEqual(out["status"], "not_applicable")
        self.assertIn("80,000", out["reason"])


class PassFailTests(unittest.TestCase):
    def setUp(self):
        self.r = VAResidualIncomeResolver()

    def test_comfortable_passes(self):
        out = self.r.qualify_va_residual(_va())  # West, family 3, residual ~5123 vs 990
        self.assertEqual(out["status"], "pass")
        self.assertTrue(out["passes"])
        self.assertEqual(out["region"], "west")

    def test_south_family1_passes(self):
        out = self.r.qualify_va_residual(_va(property_state="TX", family_size=1,
                                             qualifying_monthly=5000))
        self.assertEqual(out["region"], "south")
        self.assertEqual(out["required"], 441)
        self.assertTrue(out["passes"])

    def test_tight_income_fails_with_shortfall(self):
        out = self.r.qualify_va_residual(_va(property_state="NY", family_size=5,
                                             qualifying_monthly=3500, piti_monthly=2200,
                                             monthly_obligations=800))
        self.assertEqual(out["status"], "fail")
        self.assertEqual(out["required"], 1062)  # NE family 5
        self.assertGreater(out["shortfall"], 0)
        self.assertTrue(out["docs_needed"])


class TableAccuracyTests(unittest.TestCase):
    def setUp(self):
        self.r = VAResidualIncomeResolver()

    def test_table_values(self):
        self.assertEqual(VA_RESIDUAL_TABLE[5]["northeast"], 1062)
        self.assertEqual(VA_RESIDUAL_TABLE[5]["west"], 1158)
        self.assertEqual(VA_RESIDUAL_TABLE[1]["midwest"], 441)

    def test_per_additional_person(self):
        # family 7 West = 1158 + 2*80 = 1318
        self.assertEqual(self.r._required_residual(7, "west"), 1318)
        self.assertEqual(self.r._required_residual(6, "south"), 1039 + 80)

    def test_region_map_complete(self):
        # 50 states + DC mapped
        self.assertEqual(len(REGION_BY_STATE), 51)
        self.assertEqual(REGION_BY_STATE["TX"], "south")
        self.assertEqual(REGION_BY_STATE["CA"], "west")
        self.assertEqual(REGION_BY_STATE["NY"], "northeast")
        self.assertEqual(REGION_BY_STATE["OH"], "midwest")


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.r = VAResidualIncomeResolver()

    def test_tax_estimate(self):
        out = self.r.qualify_va_residual(_va())
        # 8000 * 25% / 12 = 166.67
        self.assertAlmostEqual(out["breakdown"]["tax_monthly"], 166.67, places=1)

    def test_maintenance_from_sqft(self):
        out = self.r.qualify_va_residual(_va(gross_living_area=1500))
        self.assertEqual(out["breakdown"]["maintenance"], 210.0)  # 1500 * 0.14

    def test_maintenance_zero_when_no_sqft(self):
        out = self.r.qualify_va_residual(_va(gross_living_area=None))
        self.assertEqual(out["breakdown"]["maintenance"], 0.0)
        self.assertTrue(any("gross_living_area" in m for m in out["missing_inputs"]))

    def test_custom_maintenance_rate_flows(self):
        r = VAResidualIncomeResolver(rules={"va_residual_maintenance_per_sqft_monthly": 0.20})
        out = r.qualify_va_residual(_va(gross_living_area=1500))
        self.assertEqual(out["breakdown"]["maintenance"], 300.0)

    def test_custom_tax_pct_flows(self):
        r = VAResidualIncomeResolver(rules={"va_residual_tax_estimate_pct": 30})
        out = r.qualify_va_residual(_va())
        self.assertAlmostEqual(out["breakdown"]["tax_monthly"], 8000 * 0.30 / 12, places=1)


class Rule11Tests(unittest.TestCase):
    def test_provenance_everywhere(self):
        r = VAResidualIncomeResolver()
        for out in (r.qualify_va_residual(_va()), r.qualify_va_residual(_va(loan_type="fha")),
                    r.qualify_va_residual(_va(family_size=None))):
            self.assertIn("data_source", out)
            self.assertIn("missing_inputs", out)
            self.assertIn("citation", out)


if __name__ == "__main__":
    unittest.main()
