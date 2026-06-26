"""Unit tests for CM-D FairLendingMonitor (pure, no DB).

Synthetic HMDA fixtures (integer codes) exercise the 4/5 disparate-impact math and
the three insufficient-data guards. RULE 11 provenance + the ECOA note asserted.
"""
import unittest

from core.compliance.fair_lending_monitor import FairLendingMonitor

# HMDA race codes: 5=White, 3=Black, 6=Not provided. action_taken: 1=originated, 3=denied.
DENY, APPROVE = 3, 1


def _rows(spec: list) -> list:
    """spec: list of (race_code, n_total, n_denied). Builds hmda_lar-shaped dicts."""
    rows, i = [], 0
    for race, total, denied in spec:
        for k in range(total):
            i += 1
            rows.append({"application_id": f"A{i}", "applicant_race": race,
                         "applicant_sex": race, "applicant_ethnicity": race,
                         "action_taken": DENY if k < denied else APPROVE})
    return rows


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.m = FairLendingMonitor()

    def test_all_not_provided(self):
        rows = _rows([(6, 40, 20)])  # race code 6 = not provided
        r = self.m.analyze_denial_rates(rows, "race")
        self.assertEqual(r["status"], "insufficient_data")
        self.assertEqual(r["reason"], "all_not_provided")
        self.assertFalse(r["has_disparate_impact"])
        self.assertTrue(r["missing_inputs"])

    def test_sample_too_small(self):
        rows = _rows([(5, 6, 1), (3, 6, 3)])  # 12 < 30
        r = self.m.analyze_denial_rates(rows, "race")
        self.assertEqual(r["status"], "insufficient_data")
        self.assertEqual(r["reason"], "sample_too_small")

    def test_single_group(self):
        rows = _rows([(5, 40, 8)])  # one usable group
        r = self.m.analyze_denial_rates(rows, "race")
        self.assertEqual(r["status"], "insufficient_data")
        self.assertEqual(r["reason"], "single_group")


class DisparityTests(unittest.TestCase):
    def setUp(self):
        self.m = FairLendingMonitor()

    def test_disparate_impact_detected(self):
        # White: 30 apps, 6 denied -> 80% approval ; Black: 20 apps, 10 denied -> 50% approval
        # ratio = 0.50/0.80 = 0.625 < 0.80 -> disparate impact
        rows = _rows([(5, 30, 6), (3, 20, 10)])
        r = self.m.analyze_denial_rates(rows, "race")
        self.assertEqual(r["status"], "disparate_impact_detected")
        self.assertTrue(r["has_disparate_impact"])
        self.assertEqual(r["reference_group"], "White")
        d = next(x for x in r["disparities"] if x["group"] == "Black/African American")
        self.assertEqual(d["four_fifths_ratio"], 0.625)
        self.assertTrue(d["disparate_impact"])

    def test_no_disparate_impact(self):
        # both groups 80% approval -> ratio 1.0
        rows = _rows([(5, 30, 6), (3, 20, 4)])
        r = self.m.analyze_denial_rates(rows, "race")
        self.assertEqual(r["status"], "no_disparate_impact")
        self.assertFalse(r["has_disparate_impact"])

    def test_custom_threshold_flows(self):
        # 0.60 approval vs 0.80 ref -> ratio 0.75. Flags at 0.80, NOT at 0.70.
        rows = _rows([(5, 30, 6), (3, 20, 8)])  # Black 8/20 denied -> 60% approval
        strict = FairLendingMonitor()  # 0.80
        lenient = FairLendingMonitor(rules={"fair_lending_four_fifths_ratio": 0.70})
        self.assertTrue(strict.analyze_denial_rates(rows, "race")["has_disparate_impact"])
        self.assertFalse(lenient.analyze_denial_rates(rows, "race")["has_disparate_impact"])

    def test_custom_min_sample_flows(self):
        rows = _rows([(5, 8, 1), (3, 8, 4)])  # 16 rows
        m = FairLendingMonitor(rules={"fair_lending_min_sample_size": 10})
        r = m.analyze_denial_rates(rows, "race")
        self.assertNotEqual(r["status"], "insufficient_data")  # 16 >= 10 now


class ExceptionGrantTests(unittest.TestCase):
    def setUp(self):
        self.m = FairLendingMonitor()

    def test_no_join_insufficient(self):
        r = self.m.analyze_exception_grant_rates([], [{"application_id": "X", "granted": True}])
        self.assertEqual(r["status"], "insufficient_data")
        self.assertEqual(r["reason"], "no_exceptions_with_demographics")

    def test_small_sample_insufficient(self):
        hmda = [{"application_id": "A1", "applicant_race": 5}]
        exc = [{"application_id": "A1", "granted": True}]
        r = self.m.analyze_exception_grant_rates(hmda, exc)
        self.assertEqual(r["status"], "insufficient_data")
        self.assertEqual(r["reason"], "sample_too_small")

    def test_complete_grant_rates(self):
        m = FairLendingMonitor(rules={"fair_lending_min_sample_size": 4})
        hmda = [{"application_id": f"A{i}", "applicant_race": 5 if i % 2 else 3} for i in range(6)]
        exc = [{"application_id": f"A{i}", "granted": i % 3 == 0} for i in range(6)]
        r = m.analyze_exception_grant_rates(hmda, exc)
        self.assertEqual(r["status"], "complete")
        self.assertEqual(r["exceptions_analyzed"], 6)
        self.assertIn("grant_rates_by_race", r)


class FullMonitorTests(unittest.TestCase):
    def test_meridian_like_insufficient(self):
        rows = _rows([(6, 16, 13)])  # all not provided, n=16
        r = FairLendingMonitor().run_full_monitor(rows, exception_rows=[])
        self.assertEqual(r["monitor_status"], "insufficient_data")
        self.assertFalse(r["has_disparate_impact"])
        self.assertIn("never uses demographic data", r["note"])
        self.assertIn("data_source", r)

    def test_disparity_rollup(self):
        rows = _rows([(5, 30, 6), (3, 20, 10)])
        r = FairLendingMonitor().run_full_monitor(rows)
        self.assertEqual(r["monitor_status"], "disparity_detected")
        self.assertTrue(r["has_disparate_impact"])

    def test_note_and_provenance_always(self):
        r = FairLendingMonitor().run_full_monitor([], exception_rows=None)
        self.assertTrue(r["note"])
        self.assertIn("citation", r)
        self.assertIn("data_source", r)
        for v in r["analyses"].values():
            self.assertIn("missing_inputs", v)


if __name__ == "__main__":
    unittest.main()
