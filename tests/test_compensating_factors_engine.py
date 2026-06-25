"""Unit tests for the EX-B CompensatingFactorsEngine. Thresholds proven to flow
from the rules dict (catalogue), SAFE_DEFAULTS fallback. RULE 11: every detect_*
returns data_source + missing_inputs."""
import unittest
from datetime import date

from core.exceptions.compensating_factors_engine import CompensatingFactorsEngine

E = CompensatingFactorsEngine()  # SAFE_DEFAULTS: 6/12 reserves, 75 ltv, 60 delta, 60mo, 10%


def _months_ago(n: int) -> str:
    t = date.today()
    y, m = t.year, t.month - n
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1).isoformat()


class ReservesTests(unittest.TestCase):
    def test_strong(self):
        r = E.detect_reserves({"total_liquid_assets": 24500, "piti_monthly": 1800})
        self.assertEqual(r["strength"], "strong")   # 13.6 >= 12
        self.assertTrue(r["present"])

    def test_weak(self):
        r = E.detect_reserves({"total_liquid_assets": 5000, "piti_monthly": 1800})
        self.assertEqual(r["strength"], "weak")      # 2.8 >= 2, < 6

    def test_piti_zero_not_applicable(self):
        r = E.detect_reserves({"total_liquid_assets": 24500, "piti_monthly": 0})
        self.assertFalse(r["present"])
        self.assertTrue(r["missing_inputs"])


class LowLtvTests(unittest.TestCase):
    def test_strong_moderate_none(self):
        self.assertEqual(E.detect_low_ltv({"ltv": 70})["strength"], "strong")    # <=75
        self.assertEqual(E.detect_low_ltv({"ltv": 78})["strength"], "moderate")  # <=80
        self.assertIsNone(E.detect_low_ltv({"ltv": 92})["strength"])
        self.assertTrue(E.detect_low_ltv({"ltv": 0})["missing_inputs"])


class CreditTests(unittest.TestCase):
    def test_strong(self):
        r = E.detect_excellent_credit({"mid_credit_score": 712, "min_credit_score_applied": 620})
        self.assertEqual(r["strength"], "strong")   # delta 92 >= 60
        self.assertEqual(r["delta"], 92)

    def test_none(self):
        r = E.detect_excellent_credit({"mid_credit_score": 640, "min_credit_score_applied": 620})
        self.assertIsNone(r["strength"])            # delta 20 < 30

    def test_no_score(self):
        self.assertTrue(E.detect_excellent_credit({})["missing_inputs"])


class EmploymentTests(unittest.TestCase):
    def test_strong(self):
        r = E.detect_long_employment({"employment_period_start": _months_ago(72)})
        self.assertEqual(r["strength"], "strong")   # >= 60

    def test_moderate(self):
        r = E.detect_long_employment({"employment_period_start": _months_ago(40)})
        self.assertEqual(r["strength"], "moderate")  # >= 36, < 60

    def test_none_short(self):
        r = E.detect_long_employment({"employment_period_start": _months_ago(24)})
        self.assertIsNone(r["strength"])            # < 36

    def test_no_date(self):
        self.assertTrue(E.detect_long_employment({})["missing_inputs"])


class LimitedDebtTests(unittest.TestCase):
    def test_strong(self):
        r = E.detect_limited_debt({"monthly_obligations": 200, "qualifying_monthly": 8000})
        self.assertEqual(r["strength"], "strong")   # 2.5% <= 10
        self.assertEqual(r["debt_pct"], 2.5)

    def test_none(self):
        r = E.detect_limited_debt({"monthly_obligations": 3000, "qualifying_monthly": 8000})
        self.assertIsNone(r["strength"])            # 37.5% > 20

    def test_no_income(self):
        self.assertTrue(E.detect_limited_debt({"monthly_obligations": 200})["missing_inputs"])


class DownPaymentTests(unittest.TestCase):
    def test_strong(self):
        r = E.detect_large_down_payment({"ltv": 75})
        self.assertEqual(r["strength"], "strong")   # 25% >= 20


class PaymentShockTests(unittest.TestCase):
    def test_always_not_applicable(self):
        r = E.detect_payment_shock({})
        self.assertFalse(r["present"])
        self.assertEqual(len(r["missing_inputs"]), 2)


class DetectAllTests(unittest.TestCase):
    def test_all_strong_senior_approval(self):
        out = E.detect_all({
            "total_liquid_assets": 24500, "piti_monthly": 1800,   # reserves strong
            "ltv": 70,                                            # low_ltv + down strong
            "mid_credit_score": 720, "min_credit_score_applied": 620,  # credit strong
            "employment_period_start": _months_ago(72),           # employment strong
            "monthly_obligations": 200, "qualifying_monthly": 8000,    # limited_debt strong
        })
        self.assertEqual(out["factors_present_count"], 6)
        self.assertEqual(out["exception_score"], 18)              # 6 x strong(3)
        self.assertEqual(out["approval_level"], "senior_uw_approval")
        self.assertEqual(out["factors_checked"], 7)

    def test_empty_insufficient(self):
        out = E.detect_all({})
        self.assertEqual(out["exception_score"], 0)
        self.assertEqual(out["approval_level"], "insufficient_factors")
        self.assertTrue(out["missing_inputs"])


class RulesInjectionTests(unittest.TestCase):
    def test_custom_exceptional_reserves_flows_through(self):
        # Custom exceptional bar = 24mo: 13.6mo is no longer "strong".
        e = CompensatingFactorsEngine(rules={"exceptional_reserves_months": 24})
        r = e.detect_reserves({"total_liquid_assets": 24500, "piti_monthly": 1800})
        self.assertEqual(r["strength"], "moderate")  # 13.6 >= 6 but < 24

    def test_custom_low_ltv_flows_through(self):
        e = CompensatingFactorsEngine(rules={"low_ltv_factor_max_pct": 60})
        self.assertIsNone(e.detect_low_ltv({"ltv": 70})["strength"])  # 70 > 60 (+5=65)


if __name__ == "__main__":
    unittest.main()
