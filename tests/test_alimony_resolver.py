"""Unit tests for the INC-F alimony / child-support resolver. Thresholds proven
to come from the rules dict (catalogue), SAFE_DEFAULTS as fallback."""
import unittest

from core.income.alimony_resolver import (
    ALIMONY_RULE_KEYS,
    AlimonyChildSupportResolver,
)

R = AlimonyChildSupportResolver()  # no rules -> rule_loader.SAFE_DEFAULTS (36/36/monthly_debt)


class AlimonyReceivedTests(unittest.TestCase):
    def test_qualifies_with_continuance(self):
        r = R.qualify_alimony_received({"alimony_monthly": 2000, "alimony_receiving": True,
                                        "continuance_months_remaining": 48})
        self.assertEqual(r["qualifying_monthly"], 2000.0)
        self.assertEqual(r["annual_amount"], 24000.0)
        self.assertEqual(r["income_type"], "ALIMONY")

    def test_excluded_short_continuance(self):
        r = R.qualify_alimony_received({"alimony_monthly": 2000, "alimony_receiving": True,
                                        "continuance_months_remaining": 24})
        self.assertEqual(r["qualifying_monthly"], 0)
        self.assertIn("excluded_reason", r)
        self.assertTrue(r["docs_needed"])

    def test_not_receiving_na(self):
        r = R.qualify_alimony_received({"alimony_monthly": 2000, "alimony_receiving": False})
        self.assertEqual(r["qualifying_monthly"], 0)
        self.assertEqual(r["method"], "alimony_not_applicable")

    def test_zero_amount_na(self):
        r = R.qualify_alimony_received({"alimony_receiving": True, "alimony_monthly": 0})
        self.assertEqual(r["qualifying_monthly"], 0)
        self.assertEqual(r["method"], "alimony_not_applicable")


class ChildSupportReceivedTests(unittest.TestCase):
    def test_qualifies_when_receiving(self):
        r = R.qualify_child_support_received({"child_support_monthly": 1500,
                                              "child_support_paying": False,
                                              "continuance_months_remaining": 40})
        self.assertEqual(r["qualifying_monthly"], 1500.0)
        self.assertEqual(r["income_type"], "CHILD_SUPPORT")

    def test_excluded_short_continuance(self):
        r = R.qualify_child_support_received({"child_support_monthly": 1500,
                                              "child_support_paying": False,
                                              "continuance_months_remaining": 20})
        self.assertEqual(r["qualifying_monthly"], 0)
        self.assertIn("excluded_reason", r)

    def test_paying_na(self):
        r = R.qualify_child_support_received({"child_support_monthly": 1500,
                                              "child_support_paying": True})
        self.assertEqual(r["qualifying_monthly"], 0)
        self.assertEqual(r["method"], "child_support_not_applicable")


class PaidTreatmentTests(unittest.TestCase):
    def test_alimony_paid_monthly_debt_default(self):
        # paying = not alimony_receiving; treatment default = monthly_debt
        r = R.treat_alimony_paid({"alimony_monthly": 2000, "alimony_receiving": False})
        self.assertEqual(r["treatment"], "monthly_debt")
        self.assertEqual(r["monthly_obligation"], 2000.0)
        self.assertEqual(r["income_reduction"], 0)

    def test_alimony_paid_reduce_income_treatment(self):
        r2 = AlimonyChildSupportResolver(rules={"alimony_paid_dti_treatment": "reduce_income"})
        r = r2.treat_alimony_paid({"alimony_monthly": 2000, "alimony_receiving": False})
        self.assertEqual(r["treatment"], "reduce_income")
        self.assertEqual(r["income_reduction"], 2000.0)
        self.assertEqual(r["monthly_obligation"], 0)

    def test_alimony_paid_not_paying_na(self):
        r = R.treat_alimony_paid({"alimony_monthly": 2000, "alimony_receiving": True})
        self.assertEqual(r["treatment"], "not_applicable")

    def test_child_support_paid_monthly_debt(self):
        r = R.treat_child_support_paid({"child_support_monthly": 1500,
                                        "child_support_paying": True})
        self.assertEqual(r["treatment"], "monthly_debt")
        self.assertEqual(r["monthly_obligation"], 1500.0)

    def test_child_support_paid_not_paying_na(self):
        r = R.treat_child_support_paid({"child_support_monthly": 1500,
                                        "child_support_paying": False})
        self.assertEqual(r["treatment"], "not_applicable")


class RulesInjectionTests(unittest.TestCase):
    def test_custom_continuance_flows_through(self):
        # Custom 48-month requirement: a 40-month continuance now FAILS.
        r48 = AlimonyChildSupportResolver(
            rules={"alimony_continuance_months_required": 48})
        out = r48.qualify_alimony_received({"alimony_monthly": 2000,
                                            "alimony_receiving": True,
                                            "continuance_months_remaining": 40})
        self.assertEqual(out["qualifying_monthly"], 0)
        self.assertIn("48mo required", out["excluded_reason"])

    def test_custom_child_support_continuance_flows_through(self):
        r30 = AlimonyChildSupportResolver(
            rules={"child_support_continuance_months_required": 30})
        out = r30.qualify_child_support_received({"child_support_monthly": 1500,
                                                  "child_support_paying": False,
                                                  "continuance_months_remaining": 30})
        self.assertEqual(out["qualifying_monthly"], 1500.0)  # 30 >= 30

    def test_rule_keys_count(self):
        self.assertEqual(len(ALIMONY_RULE_KEYS), 3)


if __name__ == "__main__":
    unittest.main()
