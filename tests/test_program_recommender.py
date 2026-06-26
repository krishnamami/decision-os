"""Unit tests for EX2-B ProgramRecommender (pure, no DB).

Profiles mirror real meridian apps. Verifies eligibility, the actionable gap math
(credit / dti / down-payment), near-miss ranking, the VA veteran gate, overlay
tightening, and RULE 11 provenance.
"""
import unittest

from core.products.program_recommender import PRODUCT_MATRIX, ProgramRecommender


def _profile(score=729, dti=42.0, ltv=86.7, loan=374000.0, income=8000.0,
             piti=2557.0, oblig=800.0, loan_type="conventional", veteran=False):
    return {"mid_credit_score": score, "dti_back": dti, "ltv": ltv, "loan_amount": loan,
            "qualifying_monthly": income, "piti_monthly": piti, "monthly_obligations": oblig,
            "loan_type": loan_type, "is_veteran": veteran}


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.r = ProgramRecommender()

    def test_sc16_multiple_eligible(self):
        res = self.r.recommend(_profile())  # 729 / 42 / 86.7
        names = {p["product_id"] for p in res["eligible_products"]}
        self.assertIn("CONV_CONFORMING", names)
        self.assertIn("FHA_30", names)
        # Jumbo: ltv 86.7 > 80 -> near-miss (down-payment gap), not eligible
        self.assertNotIn("JUMBO", names)
        self.assertEqual(res["top_recommendation"]["product_id"], "CONV_CONFORMING")

    def test_sc16_jumbo_near_miss_down_payment(self):
        res = self.r.recommend(_profile())
        jumbo = next((p for p in res["near_miss_products"] if p["product_id"] == "JUMBO"), None)
        self.assertIsNotNone(jumbo)
        ltv_gap = next(g for g in jumbo["gaps"] if g["dimension"] == "ltv")
        self.assertGreater(ltv_gap["additional_down"], 0)

    def test_sc08_fha_two_points_short(self):
        res = self.r.recommend(_profile(score=578, dti=83.0, ltv=92.0, loan=535500, income=11250))
        fha = next(p for p in (res["near_miss_products"] + res["ineligible_products"])
                   if p["product_id"] == "FHA_30")
        credit_gap = next(g for g in fha["gaps"] if g["dimension"] == "credit_score")
        self.assertEqual(credit_gap["gap"], 2)  # 580 - 578
        self.assertEqual(res["eligible_count"], 0)

    def test_sc06_no_eligible_high_dti(self):
        res = self.r.recommend(_profile(score=627, dti=64.0, ltv=95.0, loan=308750, income=6500))
        self.assertEqual(res["eligible_count"], 0)
        # there IS a gap surfaced somewhere
        self.assertTrue(res["near_miss_products"] or res["ineligible_products"])

    def test_sc03_null_dti_not_applicable(self):
        res = self.r.recommend(_profile(dti=None))
        self.assertEqual(res["eligible_count"], 0)
        self.assertEqual(len(res["not_applicable"]), len(PRODUCT_MATRIX))
        self.assertTrue(any("dti_back" in m for m in res["missing_inputs"]))


class GapMathTests(unittest.TestCase):
    def setUp(self):
        self.r = ProgramRecommender()

    def test_credit_gap_is_required_minus_current(self):
        res = self.r.evaluate_product(_profile(score=600),
                                      next(p for p in PRODUCT_MATRIX if p["product_id"] == "CONV_CONFORMING"))
        g = next(x for x in res["gaps"] if x["dimension"] == "credit_score")
        self.assertEqual(g["gap"], 20)  # 620 - 600

    def test_dti_action_present(self):
        res = self.r.evaluate_product(_profile(dti=55.0),
                                      next(p for p in PRODUCT_MATRIX if p["product_id"] == "CONV_CONFORMING"))
        g = next(x for x in res["gaps"] if x["dimension"] == "dti")
        self.assertIn("Reduce monthly debt", g["action"])
        self.assertGreaterEqual(g["excess_pct"], 9.9)

    def test_additional_down_positive_when_ltv_over(self):
        res = self.r.evaluate_product(_profile(ltv=95.0),
                                      next(p for p in PRODUCT_MATRIX if p["product_id"] == "JUMBO"))
        g = next(x for x in res["gaps"] if x["dimension"] == "ltv")
        self.assertGreater(g["additional_down"], 0)


class GatesAndRankingTests(unittest.TestCase):
    def setUp(self):
        self.r = ProgramRecommender()

    def test_va_requires_veteran(self):
        va = next(p for p in PRODUCT_MATRIX if p["product_id"] == "VA_30")
        non_vet = self.r.evaluate_product(_profile(score=700, dti=35.0, ltv=90.0), va)
        self.assertEqual(non_vet["status"], "ineligible")
        self.assertEqual(non_vet["reason"], "veteran_status_required")
        vet = self.r.evaluate_product(_profile(score=700, dti=35.0, ltv=90.0, veteran=True), va)
        self.assertTrue(vet["eligible"])

    def test_near_miss_ranked_by_score(self):
        res = self.r.recommend(_profile(score=578, dti=83.0, ltv=92.0, loan=535500, income=11250))
        scores = [p["near_miss_score"] for p in res["near_miss_products"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_overlay_tightens_threshold(self):
        r = ProgramRecommender(overlay_rules={"conv_conforming_min_score": 740})
        cc = next(p for p in PRODUCT_MATRIX if p["product_id"] == "CONV_CONFORMING")
        res = r.evaluate_product(_profile(score=729), cc)  # 729 < tightened 740
        self.assertFalse(res["eligible"])
        self.assertTrue(any(g["dimension"] == "credit_score" for g in res["gaps"]))


class Rule11Tests(unittest.TestCase):
    def test_provenance_on_every_product(self):
        res = ProgramRecommender().recommend(_profile())
        allp = (res["eligible_products"] + res["near_miss_products"]
                + res["ineligible_products"] + res["not_applicable"])
        self.assertEqual(len(allp), len(PRODUCT_MATRIX))
        for p in allp:
            self.assertIn("data_source", p)
            self.assertIn("missing_inputs", p)
            self.assertIn("citation", p)
        self.assertIn("citation", res)
        self.assertIn("data_source", res)


if __name__ == "__main__":
    unittest.main()
