"""MR-B — inventory + drift tests (pure, no DB).

PSI math + drift classification on synthetic distributions, the inventory roll-up
(reuses MR-A registry), and the per-model monitoring assessment. RULE 11 asserted.
"""
import unittest

from core.model_risk.drift import compute_psi, detect_drift
from core.model_risk.inventory import assess_model_monitoring, build_inventory


class PsiTests(unittest.TestCase):
    def test_identical_zero(self):
        s = [700 + (i % 50) for i in range(200)]
        self.assertLess(compute_psi(s, list(s)), 0.01)

    def test_shifted_significant(self):
        baseline = [620 + (i % 40) for i in range(200)]   # ~620-659
        recent = [740 + (i % 40) for i in range(200)]     # ~740-779 (big shift)
        psi = compute_psi(baseline, recent)
        self.assertGreaterEqual(psi, 0.25)

    def test_empty_none(self):
        self.assertIsNone(compute_psi([], [1, 2, 3]))

    def test_no_spread_zero(self):
        self.assertEqual(compute_psi([700] * 20, [700] * 20), 0.0)


class DetectDriftTests(unittest.TestCase):
    def test_insufficient_sample(self):
        out = detect_drift([700, 710], [720, 730])
        self.assertEqual(out["status"], "insufficient_data")
        self.assertTrue(out["missing_inputs"])

    def test_no_drift(self):
        s = [700 + (i % 50) for i in range(100)]
        out = detect_drift(s, list(s))
        self.assertEqual(out["status"], "no_drift")
        self.assertLess(out["psi"], 0.10)

    def test_significant_drift(self):
        baseline = [620 + (i % 40) for i in range(100)]
        recent = [760 + (i % 40) for i in range(100)]
        out = detect_drift(baseline, recent)
        self.assertEqual(out["status"], "significant_drift")
        self.assertGreaterEqual(out["psi"], 0.25)

    def test_rule11(self):
        out = detect_drift([700 + (i % 30) for i in range(50)], [700 + (i % 30) for i in range(50)])
        self.assertIn("data_source", out)
        self.assertIn("missing_inputs", out)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.inv = build_inventory()

    def test_fourteen_models(self):
        self.assertEqual(self.inv["total_models"], 14)
        self.assertEqual(len(self.inv["items"]), 14)

    def test_tier_rollup_matches_real(self):
        self.assertEqual(self.inv["by_tier"], {"high": 4, "medium": 7, "low": 3})

    def test_by_owner_and_plan(self):
        self.assertTrue(self.inv["by_owner"])
        self.assertIn("high", self.inv["monitoring_plan"])

    def test_rule11(self):
        self.assertIn("data_source", self.inv)
        self.assertIn("missing_inputs", self.inv)


class MonitoringAssessmentTests(unittest.TestCase):
    def test_significant_drift_attention(self):
        out = assess_model_monitoring("credit_assessment",
                                      drift={"status": "significant_drift", "psi": 0.4})
        self.assertEqual(out["overall_monitoring_status"], "attention")

    def test_moderate_watch(self):
        out = assess_model_monitoring("dti_calculation", drift={"status": "moderate_drift"})
        self.assertEqual(out["overall_monitoring_status"], "watch")

    def test_no_drift_healthy(self):
        out = assess_model_monitoring("ltv_assessment", drift={"status": "no_drift"})
        self.assertEqual(out["overall_monitoring_status"], "healthy")

    def test_insufficient(self):
        out = assess_model_monitoring("credit_assessment", drift={"status": "insufficient_data"})
        self.assertEqual(out["overall_monitoring_status"], "insufficient_data")
        self.assertTrue(out["missing_inputs"])

    def test_accuracy_and_challenger_dimensions(self):
        out = assess_model_monitoring("credit_assessment", drift={"status": "no_drift"})
        self.assertIn("accuracy", out)
        self.assertIn("champion_challenger", out)
        self.assertIn("QA-B", out["accuracy"]["note"])
        self.assertIn("CI-B", out["champion_challenger"]["note"])

    def test_rule11(self):
        out = assess_model_monitoring("credit_assessment", drift={"status": "no_drift"})
        self.assertIn("data_source", out)
        self.assertIn("missing_inputs", out)


if __name__ == "__main__":
    unittest.main()
