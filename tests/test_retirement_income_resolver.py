"""Unit tests for the INC-E retirement / SS / asset-depletion / investment
resolver. All thresholds proven to come from the rules dict (catalogue), with
SAFE_DEFAULTS as the fallback."""
import unittest

from core.income.retirement_income_resolver import (
    RETIREMENT_INCOME_RULE_KEYS,
    RetirementIncomeResolver,
)

R = RetirementIncomeResolver()  # no rules -> rule_loader.SAFE_DEFAULTS


class SocialSecurityTests(unittest.TestCase):
    def test_non_taxable_grossed_up(self):
        r = R.qualify_ss({"monthly_benefit": 2000, "is_non_taxable": True})
        self.assertEqual(r["qualifying_monthly"], 2500.0)  # 2000 x 1.25
        self.assertTrue(r["gross_up_applied"])
        self.assertEqual(r["income_type"], "SOCIAL_SECURITY")

    def test_taxable_no_gross_up(self):
        r = R.qualify_ss({"monthly_benefit": 2000, "is_non_taxable": False})
        self.assertEqual(r["qualifying_monthly"], 2000.0)
        self.assertFalse(r["gross_up_applied"])

    def test_continuance_too_short_excluded(self):
        r = R.qualify_ss({"monthly_benefit": 2000,
                          "continuance_months_remaining": 12})
        self.assertEqual(r["qualifying_monthly"], 0)
        self.assertIn("excluded_reason", r)
        self.assertTrue(r["docs_needed"])

    def test_no_benefit_excluded(self):
        r = R.qualify_ss({})
        self.assertEqual(r["qualifying_monthly"], 0)
        self.assertEqual(r["confidence"], 0)
        self.assertTrue(r["docs_needed"])


class PensionTests(unittest.TestCase):
    def test_sufficient_continuance(self):
        r = R.qualify_pension({"monthly_amount": 3000,
                               "continuance_months_remaining": 60})
        self.assertEqual(r["qualifying_monthly"], 3000.0)
        self.assertEqual(r["income_type"], "RETIREMENT")

    def test_short_continuance_excluded(self):
        r = R.qualify_pension({"monthly_amount": 3000,
                               "continuance_months_remaining": 24})
        self.assertEqual(r["qualifying_monthly"], 0)
        self.assertIn("excluded_reason", r)

    def test_no_amount_excluded(self):
        r = R.qualify_pension({})
        self.assertEqual(r["qualifying_monthly"], 0)
        self.assertTrue(r["docs_needed"])


class AssetDepletionTests(unittest.TestCase):
    def test_cash_360k_yields_1000(self):
        r = R.qualify_asset_depletion({"cash_savings": 360000})
        self.assertEqual(r["qualifying_monthly"], 1000.0)  # 360000/360
        self.assertEqual(r["eligible_cash"], 360000.0)     # 100% haircut

    def test_retirement_haircut_70pct(self):
        r = R.qualify_asset_depletion({"retirement_assets": 100000})
        self.assertEqual(r["eligible_retirement"], 70000.0)   # 70%
        self.assertEqual(r["qualifying_monthly"], 194.44)     # 70000/360

    def test_equity_haircut_and_subtractions(self):
        r = R.qualify_asset_depletion({
            "equity_assets": 100000, "down_payment_used": 20000,
            "closing_costs_used": 5000})
        # 70000 eligible - 25000 used = 45000 / 360 = 125.0
        self.assertEqual(r["qualifying_monthly"], 125.0)

    def test_zero_assets(self):
        r = R.qualify_asset_depletion({})
        self.assertEqual(r["qualifying_monthly"], 0)
        self.assertTrue(r["docs_needed"])


class DividendInterestTests(unittest.TestCase):
    def test_sufficient_history_two_year_avg(self):
        r = R.qualify_dividends_interest({
            "dividends_year1": 1200, "dividends_year2": 1200,
            "interest_year1": 0, "interest_year2": 0, "history_months": 24})
        self.assertEqual(r["qualifying_monthly"], 100.0)  # 2400/24
        self.assertEqual(r["income_type"], "INVESTMENT")

    def test_short_history_excluded(self):
        r = R.qualify_dividends_interest({
            "dividends_year1": 1200, "history_months": 18})
        self.assertEqual(r["qualifying_monthly"], 0)
        self.assertIn("excluded_reason", r)


class RulesInjectionTests(unittest.TestCase):
    def test_custom_gross_up_factor_flows_through(self):
        r = RetirementIncomeResolver(rules={"ss_non_taxable_gross_up_factor": 1.15})
        out = r.qualify_ss({"monthly_benefit": 2000, "is_non_taxable": True})
        self.assertEqual(out["qualifying_monthly"], 2300.0)  # 2000 x 1.15
        self.assertEqual(out["gross_up_factor"], 1.15)

    def test_custom_divisor_flows_through(self):
        r = RetirementIncomeResolver(rules={"asset_depletion_divisor_months": 240})
        out = r.qualify_asset_depletion({"cash_savings": 240000})
        self.assertEqual(out["qualifying_monthly"], 1000.0)  # 240000/240
        self.assertEqual(out["depletion_divisor"], 240)

    def test_rule_keys_count(self):
        self.assertEqual(len(RETIREMENT_INCOME_RULE_KEYS), 8)


if __name__ == "__main__":
    unittest.main()
