"""Unit tests for CM-F OverlayDisparityAnalyzer (pure, no DB).

Overlay-only attribution: among loans that PASS the agency floor, does a protected
class FAIL the stricter overlay at a disproportionate rate? Reuses CI-A's gate
mapping + CM-D's demographic codes. RULE 11 + honest insufficient_data asserted.
race codes: 5=White, 3=Black, 6=Not provided. sex: 1=Male, 2=Female, 3=Not provided.
"""
import unittest

from core.compliance.hmda_disparate_impact import OverlayDisparityAnalyzer

CREDIT_OVERLAY = [{"rule_type": "credit_floor", "overlay_value": 660}]
FLOORS = {"credit_floor": 620, "dti_back_max": 50, "ltv_max_purchase": 97}


def _loan(score, race=5, sex=1):
    return {"mid_credit_score": score, "applicant_race": race, "applicant_sex": sex}


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.a = OverlayDisparityAnalyzer()

    def test_disparate_impact_attributed_to_overlay(self):
        # White: score 700 (pass overlay); Black: 640 (pass agency 620, fail overlay 660)
        loans = ([_loan(700, race=5) for _ in range(6)]
                 + [_loan(640, race=3) for _ in range(6)])
        out = self.a.analyze(loans, CREDIT_OVERLAY, FLOORS)
        self.assertEqual(out["status"], "disparity_detected")
        self.assertIn("credit_floor", out["flagged_overlays"])
        res = out["results"][0]
        self.assertTrue(res["by_class"]["race"]["has_disparate_impact"])

    def test_clean_when_equal(self):
        loans = ([_loan(700, race=5) for _ in range(6)]
                 + [_loan(700, race=3) for _ in range(6)])
        out = self.a.analyze(loans, CREDIT_OVERLAY, FLOORS)
        self.assertEqual(out["status"], "clean")
        self.assertEqual(out["flagged_overlays"], [])

    def test_agency_failers_excluded(self):
        # Black all score 600 (fail agency 620) -> not overlay-attributable -> excluded
        loans = ([_loan(700, race=5) for _ in range(6)]
                 + [_loan(600, race=3) for _ in range(6)])
        out = self.a.analyze(loans, CREDIT_OVERLAY, FLOORS)
        # only White remains identifiable among agency-passers -> insufficient (single group)
        self.assertEqual(out["results"][0]["by_class"]["race"]["status"], "insufficient_data")

    def test_insufficient_all_not_provided(self):
        loans = [_loan(640, race=6) for _ in range(16)]  # all not-provided (meridian-like)
        out = self.a.analyze(loans, CREDIT_OVERLAY, FLOORS)
        self.assertEqual(out["status"], "insufficient_data")
        self.assertEqual(out["results"][0]["by_class"]["race"]["status"], "insufficient_data")

    def test_missing_agency_floor_not_applicable(self):
        out = self.a.analyze([_loan(640, race=3) for _ in range(6)], CREDIT_OVERLAY,
                             agency_floors={})  # no credit_floor agency value
        self.assertEqual(out["results"][0]["status"], "not_applicable")

    def test_dti_ceiling_direction(self):
        # dti overlay 43 (ceiling), agency 50; Black dti 47 (pass agency<=50, fail overlay<=43)
        loans = ([{"dti_back": 35, "applicant_race": 5, "applicant_sex": 1} for _ in range(6)]
                 + [{"dti_back": 47, "applicant_race": 3, "applicant_sex": 1} for _ in range(6)])
        out = self.a.analyze(loans, [{"rule_type": "dti_back_max", "overlay_value": 43}],
                             {"dti_back_max": 50})
        self.assertTrue(out["results"][0]["by_class"]["race"]["has_disparate_impact"])

    def test_strictest_overlay_chosen(self):
        # two dti overlays 43 + 50; ceiling -> strictest = 43
        loans = [{"dti_back": 47, "applicant_race": 3, "applicant_sex": 1} for _ in range(6)] + \
                [{"dti_back": 35, "applicant_race": 5, "applicant_sex": 1} for _ in range(6)]
        out = self.a.analyze(loans, [{"rule_type": "dti_back_max", "overlay_value": 43},
                                     {"rule_type": "dti_back_max", "overlay_value": 50}],
                             {"dti_back_max": 50})
        self.assertEqual(out["results"][0]["overlay_value"], 43)

    def test_thresholds_reported(self):
        out = self.a.analyze([_loan(700) for _ in range(6)], CREDIT_OVERLAY, FLOORS)
        self.assertEqual(out["thresholds"]["four_fifths_ratio"], 0.80)
        self.assertEqual(out["thresholds"]["overlay_disparity_pp"], 20)

    def test_custom_threshold_from_rules(self):
        a = OverlayDisparityAnalyzer(rules={"fair_lending_overlay_disparity_pct": 5})
        self.assertEqual(a._disparity_pp, 5.0)

    def test_rule11_provenance(self):
        out = self.a.analyze([_loan(700, race=5) for _ in range(6)]
                             + [_loan(640, race=3) for _ in range(6)], CREDIT_OVERLAY, FLOORS)
        self.assertIn("data_source", out)
        self.assertIn("missing_inputs", out)
        self.assertIn("note", out)


if __name__ == "__main__":
    unittest.main()
