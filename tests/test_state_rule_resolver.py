"""Unit tests for CM-E StateRuleResolver (pure, no DB).

Synthetic state-rule rows (the shape load_state_rules returns) exercise the typed
dispatch: threshold compute (min/max + breach + loan_purpose scoping), requirement
-> needs_review, missing field -> not_applicable, and the resolve() roll-up.
RULE 11 provenance asserted; advisory-only (never blocks).
"""
import unittest

from core.compliance.state_rule_resolver import StateRuleResolver

RULES = [
    {"rule_name": "Texas Cash-Out Refinance LTV", "state_code": "TX",
     "citation": "TX Const. XVI §50(a)(6)",
     "rule_value": {"type": "threshold", "operator": "max", "field": "ltv",
                    "value": 80, "loan_purpose": "cash_out"}},
    {"rule_name": "Texas Home Equity Cooling Period", "state_code": "TX",
     "citation": "TX Const. XVI §50(a)(6)(M)",
     "rule_value": {"type": "threshold", "unit": "days", "value": 12}},  # no field -> n/a
    {"rule_name": "New York Usury Cap", "state_code": "NY", "citation": "NY Banking Law §14-a",
     "rule_value": {"type": "threshold", "operator": "max", "field": "note_rate_pct", "value": 16}},
    {"rule_name": "anti_flipping_min_ownership_months", "state_code": "NY", "citation": "NY RPAPL 1304",
     "rule_value": {"type": "threshold", "operator": "min", "field": "months_owned", "value": 12}},
    {"rule_name": "high_cost_loan_points_fee_pct_max", "state_code": "NJ", "citation": "NJ HOSA",
     "rule_value": {"type": "threshold", "operator": "max", "field": "points_fees_pct", "value": 6}},
    {"rule_name": "high_cost_income_doc_required", "state_code": "MA", "citation": "209 CMR 32",
     "rule_value": {"type": "requirement", "value": "full_income_docs"}},
    {"rule_name": "hpml_prepayment_penalty_prohibited", "state_code": "CA", "citation": "CA Fin §4970",
     "rule_value": {"type": "prohibition", "value": "no_prepay"}},
]


class EvaluateRuleTests(unittest.TestCase):
    def setUp(self):
        self.r = StateRuleResolver(RULES)

    def _rule(self, name):
        return next(x for x in RULES if x["rule_name"] == name)

    def test_threshold_max_violation(self):
        out = self.r.evaluate_rule(self._rule("New York Usury Cap"), {"note_rate_pct": 17.0})
        self.assertEqual(out["status"], "violation")
        self.assertEqual(out["breach"], 1.0)
        self.assertTrue(out["docs_needed"])

    def test_threshold_max_pass(self):
        out = self.r.evaluate_rule(self._rule("New York Usury Cap"), {"note_rate_pct": 7.5})
        self.assertEqual(out["status"], "pass")
        self.assertEqual(out["docs_needed"], [])

    def test_threshold_min_violation(self):
        out = self.r.evaluate_rule(self._rule("anti_flipping_min_ownership_months"), {"months_owned": 6})
        self.assertEqual(out["status"], "violation")
        self.assertEqual(out["breach"], 6.0)

    def test_threshold_min_pass(self):
        out = self.r.evaluate_rule(self._rule("anti_flipping_min_ownership_months"), {"months_owned": 18})
        self.assertEqual(out["status"], "pass")

    def test_requirement_needs_review(self):
        out = self.r.evaluate_rule(self._rule("high_cost_income_doc_required"), {})
        self.assertEqual(out["status"], "needs_review")
        self.assertTrue(out["missing_inputs"])

    def test_prohibition_needs_review(self):
        out = self.r.evaluate_rule(self._rule("hpml_prepayment_penalty_prohibited"), {})
        self.assertEqual(out["status"], "needs_review")

    def test_missing_field_not_applicable(self):
        out = self.r.evaluate_rule(self._rule("New York Usury Cap"), {})  # no note_rate_pct
        self.assertEqual(out["status"], "not_applicable")
        self.assertTrue(any("note_rate_pct" in m for m in out["missing_inputs"]))

    def test_no_field_threshold_not_applicable(self):
        out = self.r.evaluate_rule(self._rule("Texas Home Equity Cooling Period"), {"ltv": 90})
        self.assertEqual(out["status"], "not_applicable")

    def test_loan_purpose_scoping(self):
        tx = self._rule("Texas Cash-Out Refinance LTV")
        # cash-out: applies
        v = self.r.evaluate_rule(tx, {"ltv": 85}, loan_purpose="cash_out_refinance")
        self.assertEqual(v["status"], "violation")
        # purchase: cash-out cap must NOT apply
        p = self.r.evaluate_rule(tx, {"ltv": 85}, loan_purpose="purchase")
        self.assertEqual(p["status"], "not_applicable")


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.r = StateRuleResolver(RULES)

    def test_no_property_state(self):
        out = self.r.resolve("", {"ltv": 90})
        self.assertEqual(out["status"], "not_applicable")
        self.assertIsNone(out["state_rules_passed"])
        self.assertTrue(out["missing_inputs"])

    def test_unknown_state_passes_clean(self):
        out = self.r.resolve("AZ", {"ltv": 99})
        self.assertEqual(out["applicable_rules"], 0)
        self.assertTrue(out["state_rules_passed"])  # no rules -> nothing to fail

    def test_tx_cashout_violation(self):
        out = self.r.resolve("TX", {"ltv": 85}, loan_purpose="cash_out_refinance")
        self.assertEqual(out["status"], "violations_found")
        self.assertFalse(out["state_rules_passed"])
        self.assertEqual(len(out["violations"]), 1)
        self.assertTrue(out["docs_needed"])

    def test_tx_purchase_clean(self):
        out = self.r.resolve("TX", {"ltv": 85}, loan_purpose="purchase")
        self.assertEqual(len(out["violations"]), 0)
        self.assertTrue(out["state_rules_passed"])

    def test_tx_note_documents_rule1_gap(self):
        out = self.r.resolve("TX", {"ltv": 75}, loan_purpose="cash_out_refinance")
        self.assertIn("hardcoded", out["note"])

    def test_ny_multiple_rules(self):
        out = self.r.resolve("NY", {"note_rate_pct": 17.0, "months_owned": 6}, loan_purpose="refinance")
        self.assertEqual(len(out["violations"]), 2)  # usury + anti-flip
        self.assertFalse(out["state_rules_passed"])

    def test_ma_requirement_needs_review(self):
        out = self.r.resolve("MA", {})
        self.assertEqual(out["state_rules_passed"], True)  # needs_review is not a violation
        self.assertEqual(len(out["needs_review"]), 1)

    def test_rule11_everywhere(self):
        for out in (self.r.resolve("TX", {"ltv": 85}, "cash_out"),
                    self.r.resolve("", {}), self.r.resolve("AZ", {})):
            self.assertIn("data_source", out)
            self.assertIn("missing_inputs", out)


if __name__ == "__main__":
    unittest.main()
