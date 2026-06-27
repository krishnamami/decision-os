"""QA-B — model accuracy backtesting tests (pure, no DB).

Synthetic decisions + performance labels verify the confusion matrix, metrics,
calibration, Gini, seasoning/unmatched guards, and the insufficient_data path.
"""
import unittest

from core.qa.backtesting import ModelAccuracyBacktester

LABELS = {
    "APP-001": {"status": "defaulted", "months_seasoned": 18},
    "APP-002": {"status": "performed", "months_seasoned": 24},
    "APP-003": {"status": "performed", "months_seasoned": 15},
    "APP-004": {"status": "defaulted", "months_seasoned": 20},
    "APP-005": {"status": "performed", "months_seasoned": 13},
    "APP-006": {"status": "delinquent", "months_seasoned": 16},
}
DECISIONS = [
    {"application_id": "APP-001", "outcome": "block", "confidence": 0.90},      # TP
    {"application_id": "APP-002", "outcome": "recommend", "confidence": 0.85},  # TN
    {"application_id": "APP-003", "outcome": "block", "confidence": 0.70},      # FP
    {"application_id": "APP-004", "outcome": "recommend", "confidence": 0.60},  # FN
    {"application_id": "APP-005", "outcome": "recommend", "confidence": 0.80},  # TN
    {"application_id": "APP-006", "outcome": "block", "confidence": 0.88},      # TP (delinquent)
]


class InsufficientDataTests(unittest.TestCase):
    def setUp(self):
        self.b = ModelAccuracyBacktester()

    def test_no_labels(self):
        out = self.b.backtest(DECISIONS, {}, tenant_id="meridian")
        self.assertEqual(out["status"], "insufficient_data")
        self.assertEqual(out["decisions_available"], 6)
        self.assertIn("loan_performance", out["gap_description"])
        self.assertTrue(out["missing_inputs"])

    def test_all_unmatched(self):
        out = self.b.backtest([{"application_id": "ZZZ", "outcome": "block", "confidence": 0.9}],
                              LABELS)
        self.assertEqual(out["status"], "insufficient_data")
        self.assertEqual(out["unmatched"], 1)

    def test_all_unseasoned(self):
        labels = {"APP-001": {"status": "defaulted", "months_seasoned": 3}}
        out = self.b.backtest([{"application_id": "APP-001", "outcome": "block", "confidence": 0.9}],
                              labels)
        self.assertEqual(out["status"], "insufficient_data")
        self.assertEqual(out["unseasoned"], 1)


class CompleteBacktestTests(unittest.TestCase):
    def setUp(self):
        self.out = ModelAccuracyBacktester().backtest(DECISIONS, LABELS, tenant_id="t", period="2024")

    def test_complete(self):
        self.assertEqual(self.out["status"], "complete")
        self.assertEqual(self.out["records_backtested"], 6)

    def test_confusion_matrix(self):
        cm = self.out["confusion_matrix"]
        self.assertEqual(cm, {"tp": 2, "fp": 1, "fn": 1, "tn": 2})

    def test_precision_recall(self):
        m = self.out["metrics"]
        self.assertEqual(m["precision"], round(2 / 3, 4))  # TP/(TP+FP)
        self.assertEqual(m["recall"], round(2 / 3, 4))     # TP/(TP+FN)
        self.assertEqual(m["approval_rate_pct"], 50.0)     # (FN+TN)/total
        self.assertEqual(m["default_rate_approved_pct"], round(1 / 3 * 100, 1))

    def test_calibration_buckets(self):
        cal = self.out["confidence_calibration"]
        self.assertTrue(cal)  # at least one populated band
        self.assertTrue(all("default_rate_pct" in v for v in cal.values()))

    def test_gini_computed(self):
        g = self.out["gini_coefficient"]
        self.assertIsNotNone(g)
        self.assertTrue(-1.0 <= g <= 1.0)

    def test_sr_11_7_provenance(self):
        self.assertIn("SR 11-7", self.out["citation"])
        self.assertIn("data_source", self.out)
        self.assertIn("missing_inputs", self.out)


class SeasoningMixTests(unittest.TestCase):
    def test_unseasoned_excluded_but_others_scored(self):
        labels = dict(LABELS)
        labels["APP-005"] = {"status": "performed", "months_seasoned": 3}  # drops out
        out = ModelAccuracyBacktester().backtest(DECISIONS, labels)
        self.assertEqual(out["status"], "complete")
        self.assertEqual(out["records_backtested"], 5)
        self.assertTrue(any("APP-005" in m for m in out["missing_inputs"]))

    def test_custom_seasoning_threshold(self):
        out = ModelAccuracyBacktester().backtest(DECISIONS, LABELS, min_seasoning_months=24)
        # only APP-002 (24mo) qualifies -> 1 record
        self.assertEqual(out["records_backtested"], 1)


if __name__ == "__main__":
    unittest.main()
