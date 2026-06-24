"""Unit tests for the INC-B W2 base-income resolver. Only data that actually
exists in document_index/entity_states is exercised (no overtime/bonus/commission
— those fields do not exist yet). Thresholds are proven to come from the rules
dict, not literals."""
import unittest
from datetime import date

from core.income.w2_income_resolver import VARIABLE_INCOME_TODO, W2IncomeResolver

# No rules passed -> falls back to rule_loader.SAFE_DEFAULTS (employment=24).
R = W2IncomeResolver()


def _months_ago(n: int) -> str:
    t = date.today()
    y, m = t.year, t.month - n
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1).isoformat()


class W2DocTests(unittest.TestCase):
    def test_box1_wages_to_monthly(self):
        r = R.qualify_from_w2_doc({"box1_wages": 96000, "employer_name": "Acme",
                                   "tax_year": 2025})
        self.assertEqual(r["qualifying_monthly"], 8000.0)
        self.assertEqual(r["income_type"], "W2")
        self.assertEqual(r["annual_amount"], 96000)
        self.assertEqual(r["method"], "W2 box1_wages / 12")
        self.assertEqual(r["docs_needed"], [])

    def test_no_wages_excluded(self):
        r = R.qualify_from_w2_doc({"employer_name": "Acme"})
        self.assertEqual(r["qualifying_monthly"], 0)
        self.assertEqual(r["confidence"], 0)
        self.assertIn("excluded_reason", r)
        self.assertTrue(r["docs_needed"])


class PaystubTests(unittest.TestCase):
    def test_biweekly_gross(self):
        # 3000 bi-weekly -> 3000*26/12 = 6500.0/mo
        r = R.qualify_from_paystub({"gross_pay": 3000, "pay_frequency": "bi-weekly"})
        self.assertEqual(r["qualifying_monthly"], 6500.0)
        self.assertEqual(r["annual_amount"], 78000)

    def test_monthly_gross_1x(self):
        r = R.qualify_from_paystub({"gross_pay": 8000, "pay_frequency": "monthly"})
        self.assertEqual(r["qualifying_monthly"], 8000.0)

    def test_unknown_frequency_defaults_biweekly(self):
        r = R.qualify_from_paystub({"gross_pay": 3000, "pay_frequency": "??"})
        self.assertEqual(r["qualifying_monthly"], 6500.0)  # 26x default


class EmploymentHistoryTests(unittest.TestCase):
    def test_sufficient_when_over_required(self):
        r = R.check_employment_history({"period_start": _months_ago(36)})
        self.assertTrue(r["history_sufficient"])
        self.assertEqual(r["required_months"], 24)  # from SAFE_DEFAULTS
        self.assertEqual(r["docs_needed"], [])

    def test_insufficient_when_under_required(self):
        r = R.check_employment_history({"period_start": _months_ago(12)})
        self.assertFalse(r["history_sufficient"])
        self.assertTrue(r["docs_needed"])

    def test_no_period_start(self):
        r = R.check_employment_history({})
        self.assertFalse(r["history_sufficient"])
        self.assertEqual(r["history_months"], 0)

    def test_threshold_comes_from_rules_dict(self):
        # Custom catalogue value: a 12-month history now SUFFICES.
        r12 = W2IncomeResolver(rules={"employment_history_months_required": 12})
        out = r12.check_employment_history({"period_start": _months_ago(12)})
        self.assertEqual(out["required_months"], 12)
        self.assertTrue(out["history_sufficient"])


class SelectTests(unittest.TestCase):
    def test_lesser_of_w2_and_paystub(self):
        w2 = {"qualifying_monthly": 8000, "confidence": 0.97}
        ps = {"qualifying_monthly": 6500, "confidence": 0.90}
        r = R.select_qualifying_income(w2, ps)
        self.assertEqual(r["qualifying_monthly"], 6500)  # lesser-of
        self.assertEqual(r["confidence"], 0.90)
        self.assertIn("lesser of", r["method"])

    def test_w2_only(self):
        r = R.select_qualifying_income({"qualifying_monthly": 8000, "confidence": 0.97},
                                       {"qualifying_monthly": 0})
        self.assertEqual(r["qualifying_monthly"], 8000)
        self.assertIn("W2 only", r["method"])

    def test_paystub_only(self):
        r = R.select_qualifying_income({"qualifying_monthly": 0},
                                       {"qualifying_monthly": 6500, "confidence": 0.90})
        self.assertEqual(r["qualifying_monthly"], 6500)
        self.assertIn("Paystub only", r["method"])

    def test_neither(self):
        r = R.select_qualifying_income({"qualifying_monthly": 0}, {"qualifying_monthly": 0})
        self.assertEqual(r["qualifying_monthly"], 0)


class TodoTests(unittest.TestCase):
    def test_variable_income_todo_present(self):
        self.assertIn("overtime_ytd", VARIABLE_INCOME_TODO)
        self.assertIn("bonus_ytd", VARIABLE_INCOME_TODO)


if __name__ == "__main__":
    unittest.main()
