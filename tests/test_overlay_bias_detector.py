"""Unit tests for CM-G OverlayBiasDetector (pure, no DB).

Demographics-free structural proxy-risk scoring: criterion weight + severity vs
agency floor + population exclusion. Asserts the actual scoring math, the
structural scan, dedup, and RULE 11 + the disclaimer.
"""
import unittest

from core.compliance.overlay_bias_detector import OverlayBiasDetector

FLOORS = {
    "credit_floor": {"agency_value": 620, "direction": "floor"},
    "dti_back_max": {"agency_value": 50, "direction": "ceiling"},
    "ltv_max_purchase": {"agency_value": 97, "direction": "ceiling"},
}


class SeverityTests(unittest.TestCase):
    def setUp(self):
        self.d = OverlayBiasDetector()

    def test_credit_severity(self):
        self.assertAlmostEqual(self.d._severity_score("credit_floor", 660, 620, "floor"), 0.20)
        self.assertAlmostEqual(self.d._severity_score("credit_floor", 760, 620, "floor"), 0.70)

    def test_at_floor_zero(self):
        self.assertEqual(self.d._severity_score("credit_floor", 620, 620, "floor"), 0.0)

    def test_dti_severity(self):
        # ceiling: (50-43)/30 = 0.2333
        self.assertAlmostEqual(self.d._severity_score("dti_back_max", 43, 50, "ceiling"), 7 / 30)

    def test_severity_capped(self):
        self.assertEqual(self.d._severity_score("credit_floor", 900, 620, "floor"), 1.0)


class ExclusionTests(unittest.TestCase):
    def setUp(self):
        self.d = OverlayBiasDetector()

    def test_floor_exclusion(self):
        # floor 620, overlay 660: agency-passing = all >=620; excluded = <660
        pop = [635, 645, 655, 720, 740]
        pct, n, ap = self.d._exclusion_score(660, 620, "floor", pop)
        self.assertEqual(ap, 5)
        self.assertEqual(n, 3)
        self.assertEqual(pct, 60.0)

    def test_agency_failers_not_counted(self):
        pop = [600, 610, 700]  # 600/610 fail agency 620 -> excluded from denominator
        pct, n, ap = self.d._exclusion_score(660, 620, "floor", pop)
        self.assertEqual(ap, 1)  # only 700 passes agency
        self.assertEqual(n, 0)

    def test_ceiling_exclusion(self):
        # dti ceiling: agency 50, overlay 43; pass agency = <=50; excluded = >43
        pop = [35, 45, 48, 60]  # 60 fails agency; 45,48 pass agency but exceed 43
        pct, n, ap = self.d._exclusion_score(43, 50, "ceiling", pop)
        self.assertEqual(ap, 3)
        self.assertEqual(n, 2)

    def test_empty_population(self):
        self.assertEqual(self.d._exclusion_score(660, 620, "floor", []), (0.0, 0, 0))


class ScoreOverlayTests(unittest.TestCase):
    def setUp(self):
        self.d = OverlayBiasDetector()

    def test_aggressive_overlay_high_or_elevated(self):
        # credit floor 780 vs 620 (severity 0.80), population mostly below -> high exclusion
        pop = [630, 640, 650, 660, 670, 700, 710, 790]  # 7 of 8 agency-passing excluded
        out = self.d.score_overlay("credit_floor", 780, "floor", 620, pop)
        self.assertIn(out["risk_level"], ("elevated", "high"))
        self.assertGreater(out["composite_score"], 0.55)

    def test_mild_overlay_low(self):
        # overlay 625 barely over 620, almost nobody excluded
        pop = [700, 710, 720, 730, 740]
        out = self.d.score_overlay("credit_floor", 625, "floor", 620, pop)
        self.assertEqual(out["risk_level"], "low")

    def test_no_population_missing_inputs(self):
        out = self.d.score_overlay("credit_floor", 660, "floor", 620, [])
        self.assertTrue(out["missing_inputs"])
        self.assertEqual(out["components"]["exclusion_pct"], 0.0)

    def test_recommendation_present(self):
        out = self.d.score_overlay("credit_floor", 660, "floor", 620, [700, 710])
        self.assertIn("proxy risk", out["recommendation"].lower())

    def test_rule11(self):
        out = self.d.score_overlay("credit_floor", 660, "floor", 620, [700])
        self.assertIn("data_source", out)
        self.assertIn("missing_inputs", out)


class StructuralScanTests(unittest.TestCase):
    def setUp(self):
        self.d = OverlayBiasDetector()

    def test_no_geographic_low(self):
        out = self.d.structural_scan([{"rule_type": "credit_floor"}, {"rule_type": "dti_back_max"}])
        geo = next(f for f in out["structural_findings"] if f["pattern"] == "geographic_variation")
        self.assertEqual(geo["risk"], "low")
        self.assertEqual(out["high_risk_patterns"], 0)

    def test_geographic_high(self):
        out = self.d.structural_scan([{"rule_type": "zip_code"}])
        geo = next(f for f in out["structural_findings"] if f["pattern"] == "geographic_variation")
        self.assertEqual(geo["risk"], "high")
        self.assertEqual(out["high_risk_patterns"], 1)

    def test_loan_size_elevated(self):
        out = self.d.structural_scan([{"rule_type": "min_loan_amount"}])
        self.assertTrue(any(f["pattern"] == "loan_size_minimum" for f in out["structural_findings"]))


class RunTests(unittest.TestCase):
    def setUp(self):
        self.d = OverlayBiasDetector()

    def test_dedup_strictest(self):
        overlays = [{"rule_type": "dti_back_max", "overlay_value": 50},
                    {"rule_type": "dti_back_max", "overlay_value": 43}]
        out = self.d.run(overlays, {"dti_back_max": [35, 45]}, FLOORS)
        self.assertEqual(out["overlays_scored"], 1)
        self.assertEqual(out["results"][0]["overlay_value"], 43)  # ceiling -> strictest = lowest

    def test_disclaimer_always(self):
        out = self.d.run([{"rule_type": "credit_floor", "overlay_value": 660}],
                         {"credit_floor": [700]}, FLOORS)
        self.assertIn("internal screening heuristics", out["disclaimer"])
        self.assertIn("NOT constitute a legal finding", out["disclaimer"])

    def test_structural_scan_included(self):
        out = self.d.run([{"rule_type": "credit_floor", "overlay_value": 660}],
                         {"credit_floor": [700]}, FLOORS)
        self.assertIn("structural_scan", out)
        self.assertIn("high_risk_count", out)

    def test_catalogue_weights_flow(self):
        d = OverlayBiasDetector(rules={"credit_floor_proxy_risk_weight": 0.10})
        self.assertEqual(d._weights["credit_floor"], 0.10)

    def test_rule11(self):
        out = self.d.run([{"rule_type": "credit_floor", "overlay_value": 660}],
                         {"credit_floor": [700]}, FLOORS)
        self.assertIn("data_source", out)
        self.assertIn("missing_inputs", out)


if __name__ == "__main__":
    unittest.main()
