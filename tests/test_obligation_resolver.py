"""Unit tests for the OB-A ObligationResolver. Thresholds proven to come from the
rules dict (catalogue), SAFE_DEFAULTS fallback. Student-loan + alimony routing
delegates to existing resolvers (not recomputed)."""
import unittest

from core.obligations.obligation_resolver import (
    OBLIGATION_RULE_KEYS,
    ObligationResolver,
)

R = ObligationResolver()  # no rules -> SAFE_DEFAULTS (revolving 5%, heloc 1%, excl 10)


class InstallmentTests(unittest.TestCase):
    def test_actual_payment(self):
        r = R.compute_installment({"monthly_payment": 400, "months_remaining": 36})
        self.assertEqual(r["monthly_obligation"], 400.0)
        self.assertTrue(r["included"])

    def test_balance_div_months(self):
        r = R.compute_installment({"balance": 12000, "months_remaining": 24})
        self.assertEqual(r["monthly_obligation"], 500.0)  # 12000/24

    def test_months_remaining_excluded(self):
        r = R.compute_installment({"monthly_payment": 400, "months_remaining": 8})
        self.assertFalse(r["included"])  # 8 <= 10
        self.assertIn("excluded_reason", r)


class RevolvingTests(unittest.TestCase):
    def test_reported_min_payment(self):
        r = R.compute_revolving({"minimum_payment": 50, "balance": 5000})
        self.assertEqual(r["monthly_obligation"], 50.0)

    def test_five_pct_of_balance_when_no_payment(self):
        r = R.compute_revolving({"balance": 5000})
        self.assertEqual(r["monthly_obligation"], 250.0)  # 5% of 5000


class HelocTests(unittest.TestCase):
    def test_actual_payment(self):
        r = R.compute_heloc({"monthly_payment": 300, "balance": 40000})
        self.assertEqual(r["monthly_obligation"], 300.0)

    def test_one_pct_of_balance(self):
        r = R.compute_heloc({"balance": 40000})
        self.assertEqual(r["monthly_obligation"], 400.0)  # 1% of 40000

    def test_one_pct_of_limit_when_zero_balance(self):
        r = R.compute_heloc({"balance": 0, "credit_limit": 50000})
        self.assertEqual(r["monthly_obligation"], 500.0)  # 1% of limit


class RoutingTests(unittest.TestCase):
    def test_student_loan_precomputed_included(self):
        out = R.resolve([{"type": "student_loan", "computed_payment": 250,
                          "included_in_dti": True}])
        self.assertEqual(out["total_qualifying_obligations"], 250.0)
        self.assertEqual(out["per_type"][0]["method"],
                         "student_loan_precomputed_tradeline_analyzer")

    def test_student_loan_pslf_excluded(self):
        out = R.resolve([{"type": "student_loan", "computed_payment": 0,
                          "included_in_dti": False, "exclusion_reason": "PSLF $0"}])
        self.assertEqual(out["total_qualifying_obligations"], 0)
        self.assertEqual(len(out["excluded"]), 1)

    def test_alimony_paid_monthly_debt(self):
        out = R.resolve([{"type": "alimony_paid", "alimony_monthly": 2000,
                          "alimony_receiving": False}])
        self.assertEqual(out["total_qualifying_obligations"], 2000.0)

    def test_child_support_paid(self):
        out = R.resolve([{"type": "child_support_paid", "child_support_monthly": 1500,
                          "child_support_paying": True}])
        self.assertEqual(out["total_qualifying_obligations"], 1500.0)

    def test_mixed_sum_and_exclusions(self):
        out = R.resolve([
            {"type": "installment", "monthly_payment": 400, "months_remaining": 36},
            {"type": "installment", "monthly_payment": 300, "months_remaining": 6},  # excluded
            {"type": "revolving", "balance": 5000},   # 250
            {"type": "heloc", "balance": 40000},       # 400
        ])
        self.assertEqual(out["total_qualifying_obligations"], 1050.0)  # 400+250+400
        self.assertEqual(out["obligation_count"], 4)
        self.assertEqual(len(out["excluded"]), 1)

    def test_empty(self):
        out = R.resolve([])
        self.assertEqual(out["total_qualifying_obligations"], 0)
        self.assertEqual(out["per_type"], [])


class RulesInjectionTests(unittest.TestCase):
    def test_custom_revolving_pct_flows_through(self):
        r10 = ObligationResolver(rules={"revolving_payment_factor_pct": 10})
        out = r10.compute_revolving({"balance": 5000})
        self.assertEqual(out["monthly_obligation"], 500.0)  # 10% of 5000

    def test_custom_exclusion_flows_through(self):
        r3 = ObligationResolver(rules={"months_remaining_exclusion": 3})
        out = r3.compute_installment({"monthly_payment": 400, "months_remaining": 8})
        self.assertTrue(out["included"])  # 8 > 3 now

    def test_rule_keys(self):
        self.assertIn("revolving_payment_factor_pct", OBLIGATION_RULE_KEYS)
        self.assertIn("heloc_payment_factor_pct", OBLIGATION_RULE_KEYS)


if __name__ == "__main__":
    unittest.main()
