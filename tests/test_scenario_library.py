"""Unit tests for the SC-B scenario library (pure data, no DB).

Verifies the 16 meridian scenarios load, match the authoritative key-decision
expectations, carry RULE 11 provenance, and never fabricate a condition (every
ScenarioCondition reflects a real threshold breach).
"""
import unittest

from core.scenarios import (
    BEST_DEMO_SCENARIOS,
    CREDIT_FLOOR,
    DTI_MAX,
    LTV_MAX,
    MERIDIAN_BY_APP,
    MERIDIAN_BY_ID,
    MERIDIAN_SCENARIOS,
    Scenario,
)

# The authoritative per-key-decision expectations (mirror of the eval's
# EXPECTED_OUTCOMES). The library must reproduce these exactly.
EXPECTED = {
    "SC01": ("fraud_screening", "block"),
    "SC02": ("dti_calculation", "block"),
    "SC03": ("income_verification", "recommend"),
    "SC04": ("employment_reconciliation", "escalate"),
    "SC05": ("compliance_check", "block"),
    "SC06": ("credit_assessment", "recommend"),
    "SC07": ("dti_calculation", "recommend"),
    "SC08": ("credit_assessment", "block"),
    "SC09": ("income_verification", "escalate"),
    "SC10": ("closing_readiness", "block"),
    "SC11": ("dti_calculation", "block"),
    "SC12": ("income_verification", "recommend"),
    "SC13": ("product_eligibility", "block"),
    "SC14": ("product_eligibility", "escalate"),
    "SC15": ("asset_verification", "escalate"),
    "SC16": ("closing_readiness", "escalate"),
}


class LibraryShapeTests(unittest.TestCase):
    def test_sixteen_scenarios(self):
        self.assertEqual(len(MERIDIAN_SCENARIOS), 16)
        self.assertEqual(len(MERIDIAN_BY_ID), 16)
        self.assertEqual(len(MERIDIAN_BY_APP), 16)

    def test_all_are_scenarios_with_provenance(self):
        for s in MERIDIAN_SCENARIOS:
            self.assertIsInstance(s, Scenario)
            self.assertTrue(s.data_source)
            self.assertIsInstance(s.missing_inputs, list)
            self.assertIn(s.underwriting_outcome, ("block", "escalate", "recommend"))

    def test_key_decisions_match_authoritative_expected(self):
        for sid, (dec, out) in EXPECTED.items():
            s = MERIDIAN_BY_ID[sid]
            self.assertEqual((s.expected_key_decision, s.expected_outcome), (dec, out),
                             f"{sid} key decision drifted from EXPECTED_OUTCOMES")

    def test_best_demos_present(self):
        for d in BEST_DEMO_SCENARIOS:
            self.assertIn(d, MERIDIAN_BY_ID)


class ConditionTests(unittest.TestCase):
    def test_sc08_multi_block_credit_and_dti(self):
        s = MERIDIAN_BY_ID["SC08"]
        rules = {c.rule_name for c in s.conditions}
        self.assertEqual(rules, {"min_credit_score", "dti_back_max"})
        self.assertTrue(s.is_multi_block())

    def test_sc16_clean_no_conditions(self):
        s = MERIDIAN_BY_ID["SC16"]
        self.assertEqual(s.conditions, [])
        self.assertFalse(s.is_multi_block())

    def test_conditions_are_never_fabricated(self):
        # every condition must reflect a genuine breach of its threshold
        for s in MERIDIAN_SCENARIOS:
            for c in s.conditions:
                if c.rule_name == "min_credit_score":
                    self.assertLess(c.borrower_value, CREDIT_FLOOR)
                    self.assertEqual(c.direction, "below")
                elif c.rule_name == "dti_back_max":
                    self.assertGreater(c.borrower_value, DTI_MAX)
                    self.assertEqual(c.direction, "above")
                elif c.rule_name == "ltv_max_purchase":
                    self.assertGreater(c.borrower_value, LTV_MAX)

    def test_borderline_dti_has_no_condition(self):
        # SC07/SC14/SC16 sit at dti ~42 (within the 43 overlay) -> no dti condition
        for sid in ("SC07", "SC14", "SC16"):
            self.assertNotIn("dti_back_max",
                             {c.rule_name for c in MERIDIAN_BY_ID[sid].conditions})


class Rule11Tests(unittest.TestCase):
    def test_sc03_null_dti_missing_inputs(self):
        s = MERIDIAN_BY_ID["SC03"]
        self.assertIsNone(s.dti_back)
        self.assertTrue(s.missing_inputs)
        self.assertTrue(any("dti_back" in m for m in s.missing_inputs))
        # NULL dti must NOT produce a fabricated dti condition
        self.assertNotIn("dti_back_max", {c.rule_name for c in s.conditions})

    def test_no_other_scenario_claims_missing(self):
        for s in MERIDIAN_SCENARIOS:
            if s.scenario_id != "SC03":
                self.assertEqual(s.missing_inputs, [], f"{s.scenario_id}")


class HelperTests(unittest.TestCase):
    def test_reserve_months_with_assets(self):
        # SC02 has real liquid assets -> positive reserves
        self.assertGreater(MERIDIAN_BY_ID["SC02"].reserve_months(), 0)

    def test_reserve_months_zero_when_no_assets(self):
        # SC08/SC14/SC16 have 0 liquid assets in the live fixtures
        self.assertEqual(MERIDIAN_BY_ID["SC08"].reserve_months(), 0.0)

    def test_demo_talking_points_cite_thresholds(self):
        pts = " ".join(MERIDIAN_BY_ID["SC08"].demo_talking_points())
        self.assertIn("Fannie B3-5.1-01", pts)   # credit citation
        self.assertIn("Fannie B3-6-02", pts)      # dti citation
        self.assertIn("BLOCKED", pts)

    def test_sc16_demo_reads_as_clean_recommend(self):
        pts = " ".join(MERIDIAN_BY_ID["SC16"].demo_talking_points())
        self.assertIn("Clean approval", pts)


if __name__ == "__main__":
    unittest.main()
