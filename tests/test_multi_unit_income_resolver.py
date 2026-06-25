"""Unit tests for CO-D MultiUnitIncomeResolver (pure, no DB).

Covers subject 2-4 unit (75% market rent net of PITI), ADU (HomeReady),
investment 2-4 unit (INC-D net rental), eligibility/occupancy gates, catalogue-
factor flow, and RULE 11 provenance on every method.
"""
import unittest

from core.income.multi_unit_income_resolver import (
    MULTI_UNIT_RULE_KEYS,
    MultiUnitIncomeResolver,
)


class SubjectMultiUnitTests(unittest.TestCase):
    def setUp(self):
        self.r = MultiUnitIncomeResolver()

    def test_missing_inputs_not_applicable(self):
        out = self.r.qualify_subject_multi_unit({"piti_monthly": 2693})
        self.assertEqual(out["method"], "multi_unit_subject_not_applicable")
        self.assertEqual(out["qualifying_monthly"], 0.0)
        self.assertEqual(len(out["missing_inputs"]), 2)

    def test_3_unit_negative_cash_flow_zero_income(self):
        out = self.r.qualify_subject_multi_unit({
            "num_units": 3, "gross_market_rent_per_unit": 1500,
            "piti_monthly": 2693, "occupancy_type": "primary"})
        # 2 rental units * 1500 * 75% = 2250 ; 2250 - 2693 = -443 -> qualifying 0
        self.assertEqual(out["rental_units"], 2)
        self.assertEqual(out["qualifying_rental"], 2250.0)
        self.assertEqual(out["net_cash_flow"], -443.0)
        self.assertTrue(out["is_shortfall"])
        self.assertEqual(out["qualifying_monthly"], 0.0)

    def test_2_unit_break_even(self):
        out = self.r.qualify_subject_multi_unit({
            "num_units": 2, "gross_market_rent_per_unit": 2000,
            "piti_monthly": 1500, "occupancy_type": "primary"})
        # 1 * 2000 * 75% = 1500 ; 1500 - 1500 = 0
        self.assertEqual(out["qualifying_rental"], 1500.0)
        self.assertEqual(out["qualifying_monthly"], 0.0)
        self.assertFalse(out["is_shortfall"])

    def test_4_unit_positive_income(self):
        out = self.r.qualify_subject_multi_unit({
            "num_units": 4, "gross_market_rent_per_unit": 1800,
            "piti_monthly": 2000, "occupancy_type": "primary"})
        # 3 * 1800 * 75% = 4050 ; 4050 - 2000 = 2050
        self.assertEqual(out["rental_units"], 3)
        self.assertEqual(out["qualifying_monthly"], 2050.0)

    def test_1_unit_ineligible(self):
        out = self.r.qualify_subject_multi_unit({
            "num_units": 1, "gross_market_rent_per_unit": 1500, "piti_monthly": 1000})
        self.assertEqual(out["method"], "multi_unit_subject_ineligible")

    def test_5_unit_ineligible(self):
        out = self.r.qualify_subject_multi_unit({
            "num_units": 5, "gross_market_rent_per_unit": 1500, "piti_monthly": 1000})
        self.assertEqual(out["method"], "multi_unit_subject_ineligible")

    def test_non_owner_occupied_routes_to_investment(self):
        out = self.r.qualify_subject_multi_unit({
            "num_units": 3, "gross_market_rent_per_unit": 1500,
            "piti_monthly": 2000, "occupancy_type": "investment",
            "is_owner_occupied": False})
        self.assertEqual(out["method"], "multi_unit_investment_not_subject")

    def test_custom_factor_flows(self):
        r80 = MultiUnitIncomeResolver(rules={"subject_2_4_unit_rental_factor": 80})
        out = r80.qualify_subject_multi_unit({
            "num_units": 3, "gross_market_rent_per_unit": 1500,
            "piti_monthly": 2000, "occupancy_type": "primary"})
        self.assertEqual(out["qualifying_rental"], 2400.0)  # 2*1500*0.80


class AduTests(unittest.TestCase):
    def setUp(self):
        self.r = MultiUnitIncomeResolver()

    def test_missing_inputs_not_applicable(self):
        out = self.r.qualify_adu_income({"adu_present": None, "adu_market_rent_monthly": None})
        self.assertEqual(out["method"], "adu_not_applicable")
        self.assertEqual(len(out["missing_inputs"]), 2)

    def test_present_75pct(self):
        out = self.r.qualify_adu_income({
            "adu_present": True, "adu_market_rent_monthly": 1200, "occupancy_type": "primary"})
        self.assertEqual(out["qualifying_monthly"], 900.0)
        self.assertEqual(out["citation"], "Fannie HomeReady B5-6-01 / Form 1007")

    def test_not_present(self):
        out = self.r.qualify_adu_income({
            "adu_present": False, "adu_market_rent_monthly": 1200, "occupancy_type": "primary"})
        self.assertEqual(out["method"], "adu_not_present")
        self.assertEqual(out["qualifying_monthly"], 0.0)

    def test_not_owner_occupied_excluded(self):
        out = self.r.qualify_adu_income({
            "adu_present": True, "adu_market_rent_monthly": 1200, "occupancy_type": "investment"})
        self.assertEqual(out["method"], "adu_excluded_not_owner_occupied")
        self.assertIn("excluded_reason", out)

    def test_overlay_disables_adu(self):
        r = MultiUnitIncomeResolver(rules={"adu_rental_income_allowed": False})
        out = r.qualify_adu_income({"adu_present": True, "adu_market_rent_monthly": 1200})
        self.assertEqual(out["method"], "adu_not_allowed_by_overlay")


class InvestmentTests(unittest.TestCase):
    def setUp(self):
        self.r = MultiUnitIncomeResolver()

    def test_positive(self):
        out = self.r.qualify_investment_multi_unit({
            "net_rental_income": 3000, "piti_monthly": 2000, "has_schedule_e": True, "num_units": 2})
        self.assertEqual(out["qualifying_monthly"], 1000.0)

    def test_negative_zero(self):
        out = self.r.qualify_investment_multi_unit({
            "net_rental_income": 1500, "piti_monthly": 2000, "has_schedule_e": True, "num_units": 2})
        self.assertEqual(out["qualifying_monthly"], 0.0)
        self.assertTrue(out["is_shortfall"])

    def test_no_data_not_applicable(self):
        out = self.r.qualify_investment_multi_unit({"piti_monthly": 2000})
        self.assertEqual(out["method"], "investment_multi_unit_not_applicable")
        self.assertTrue(out["missing_inputs"])


class Rule11Tests(unittest.TestCase):
    def test_every_method_has_provenance(self):
        r = MultiUnitIncomeResolver()
        results = [
            r.qualify_subject_multi_unit({"num_units": 3, "gross_market_rent_per_unit": 1500,
                                          "piti_monthly": 2000, "occupancy_type": "primary"}),
            r.qualify_subject_multi_unit({}),
            r.qualify_adu_income({"adu_present": True, "adu_market_rent_monthly": 1200,
                                  "occupancy_type": "primary"}),
            r.qualify_adu_income({}),
            r.qualify_investment_multi_unit({"net_rental_income": 3000, "piti_monthly": 2000,
                                             "has_schedule_e": True, "num_units": 2}),
        ]
        for out in results:
            self.assertIn("data_source", out)
            self.assertIn("missing_inputs", out)
            self.assertIn("citation", out)

    def test_rule_keys_include_shared_vacancy(self):
        self.assertIn("rental_vacancy_factor_pct", MULTI_UNIT_RULE_KEYS)
        self.assertIn("market_rent_qualifying_factor_pct", MULTI_UNIT_RULE_KEYS)


if __name__ == "__main__":
    unittest.main()
