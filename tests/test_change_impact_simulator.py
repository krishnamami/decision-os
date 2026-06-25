"""Unit tests for CI-A ChangeImpactSimulator.

Pure primitives (gate / reduce / persona-flip / classify) plus an integration
test against a fake asyncpg conn that returns canned rows — no live DB. The
fixtures encode the real meridian shapes: sole-constraint unblock, the SC01
shadowed-by-other-constraint case, a NULL field (RULE 11), and a tightening
that newly blocks a clean app.
"""
import asyncio
import unittest

from core.intelligence.change_impact_simulator import (
    SIMULATABLE_FIELDS,
    ChangeImpactSimulator,
    _normalize_upstream,
    _reduce_outcome,
)


class _FakeConn:
    """Minimal asyncpg-conn stand-in. fetch() dispatches on the query text."""
    def __init__(self, decisions, entities):
        self._decisions = decisions
        self._entities = entities

    async def fetch(self, query, *args):
        if "decision_outputs" in query:
            return self._decisions
        if "entity_states" in query:
            return self._entities
        return []


def _run(coro):
    return asyncio.run(coro)


def _decision(app, outcome, upstream):
    return {"application_id": app, "outcome": outcome,
            "upstream_decisions": upstream, "version": 1}


def _entity(app, **f):
    base = {"application_id": app, "loan_amount": 400000.0, "mid_credit_score": 700,
            "dti_back": 40.0, "dti_front": 30.0, "ltv": 80.0,
            "qualifying_monthly": 8000.0, "total_liquid_assets": 50000.0}
    base.update(f)
    return base


class GatePrimitiveTests(unittest.TestCase):
    def setUp(self):
        self.s = ChangeImpactSimulator()

    def test_gate_gte(self):
        self.assertTrue(self.s._evaluate_gate(660, 660, "gte"))
        self.assertFalse(self.s._evaluate_gate(659, 660, "gte"))

    def test_gate_lte(self):
        self.assertTrue(self.s._evaluate_gate(43, 43, "lte"))
        self.assertFalse(self.s._evaluate_gate(44, 43, "lte"))

    def test_gate_bad_direction(self):
        with self.assertRaises(ValueError):
            self.s._evaluate_gate(1, 1, "sideways")


class ReduceTests(unittest.TestCase):
    def test_block_dominates(self):
        self.assertEqual(_reduce_outcome(
            {"a": "recommend", "b": "block", "c": "escalate"}), "block")

    def test_escalate_over_recommend(self):
        self.assertEqual(_reduce_outcome(
            {"a": "recommend", "b": "escalate"}), "escalate")

    def test_all_clean(self):
        self.assertEqual(_reduce_outcome(
            {"a": "recommend", "b": "allow"}), "recommend")

    def test_normalize_both_shapes(self):
        self.assertEqual(_normalize_upstream({"a": "block"}), {"a": "block"})
        self.assertEqual(_normalize_upstream({"a": {"outcome": "block"}}), {"a": "block"})
        self.assertEqual(_normalize_upstream('{"a": "block"}'), {"a": "block"})


class PersonaFlipTests(unittest.TestCase):
    def setUp(self):
        self.s = ChangeImpactSimulator()

    def test_loosen_clears_only_when_gate_flips(self):
        # was failing (block), now passes -> clears
        self.assertEqual(
            self.s._simulate_persona_outcome("block", False, True), "recommend")

    def test_loosen_does_not_clear_nonthreshold_block(self):
        # already passing the field gate but persona still blocked (e.g. bankruptcy)
        # -> NOT cleared (block left intact)
        self.assertEqual(
            self.s._simulate_persona_outcome("block", True, True), "block")

    def test_tighten_blocks_clean_persona(self):
        self.assertEqual(
            self.s._simulate_persona_outcome("recommend", True, False), "block")

    def test_tighten_leaves_already_blocked(self):
        self.assertEqual(
            self.s._simulate_persona_outcome("block", False, False), "block")


class SimulateIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.s = ChangeImpactSimulator()

    def test_sole_constraint_unblock_counted(self):
        # app blocked ONLY on credit; score 650 fails at 660, passes at 640
        decisions = [_decision("A1", "block", {
            "credit_assessment": "block", "dti_calculation": "recommend",
            "ltv_assessment": "allow", "product_eligibility": "recommend"})]
        entities = [_entity("A1", mid_credit_score=650, loan_amount=300000.0)]
        r = _run(self.s.simulate(_FakeConn(decisions, entities), "t",
                                 "credit_floor", 660, 640))
        self.assertEqual(r["impact_summary"]["true_unblocks"], 1)
        self.assertEqual(r["impact_summary"]["dollars_unblocked"], 300000.0)
        self.assertEqual(r["true_unblocks"][0]["application_id"], "A1")
        self.assertTrue(r["true_unblocks"][0]["sole_binding_constraint"])

    def test_multi_constraint_shadowed_not_counted(self):
        # SC01-like: credit clears but product_eligibility still blocks
        decisions = [_decision("SC01", "block", {
            "credit_assessment": "block", "dti_calculation": "recommend",
            "product_eligibility": "block"})]
        entities = [_entity("SC01", mid_credit_score=650, loan_amount=382500.0)]
        r = _run(self.s.simulate(_FakeConn(decisions, entities), "t",
                                 "credit_floor", 660, 640))
        self.assertEqual(r["impact_summary"]["true_unblocks"], 0)
        self.assertEqual(r["impact_summary"]["shadowed_by_other_constraints"], 1)
        self.assertEqual(r["impact_summary"]["dollars_shadowed"], 382500.0)
        sh = r["shadowed"][0]
        self.assertIn("product_eligibility", sh["other_blocking_personas"])
        self.assertEqual(sh["simulated_outcome"], "block")
        self.assertFalse(sh["sole_binding_constraint"])

    def test_null_field_is_missing_input_rule11(self):
        decisions = [_decision("N1", "block", {"dti_calculation": "block"})]
        entities = [_entity("N1", dti_back=None)]
        r = _run(self.s.simulate(_FakeConn(decisions, entities), "t",
                                 "dti_back_max", 43, 50))
        self.assertEqual(r["impact_summary"]["missing_data_apps"], 1)
        self.assertIn("N1", r["missing_inputs"])
        md = r["missing_data"][0]
        self.assertTrue(md["missing_inputs"])
        self.assertIn("dti_back", md["data_source"])

    def test_tighten_creates_new_block(self):
        # clean app at dti 42 -> tighten max to 38 -> newly blocked
        decisions = [_decision("T1", "recommend", {
            "dti_calculation": "recommend", "credit_assessment": "allow"})]
        entities = [_entity("T1", dti_back=42.0, loan_amount=374000.0)]
        r = _run(self.s.simulate(_FakeConn(decisions, entities), "t",
                                 "dti_back_max", 43, 38))
        self.assertEqual(r["impact_summary"]["new_blocks"], 1)
        self.assertEqual(r["impact_summary"]["dollars_at_risk"], 374000.0)
        self.assertEqual(r["new_blocks"][0]["simulated_outcome"], "block")

    def test_unknown_rule_errors_with_missing_inputs(self):
        r = _run(self.s.simulate(_FakeConn([], []), "t", "nope", 1, 2))
        self.assertFalse(r["success"])
        self.assertIn("Unknown rule", r["error"])
        self.assertTrue(r["missing_inputs"])

    def test_provenance_on_every_result_rule11(self):
        decisions = [_decision("A1", "block", {"credit_assessment": "block"})]
        entities = [_entity("A1", mid_credit_score=650)]
        r = _run(self.s.simulate(_FakeConn(decisions, entities), "t",
                                 "credit_floor", 660, 640))
        self.assertIn("data_source", r)
        self.assertIn("honesty_caveat", r)
        for res in r["true_unblocks"] + r["shadowed"] + r["new_blocks"]:
            self.assertIn("data_source", res)
            self.assertIn("missing_inputs", res)

    def test_map_covers_three_levers(self):
        self.assertEqual(set(SIMULATABLE_FIELDS),
                         {"credit_floor", "dti_back_max", "ltv_max_purchase"})


if __name__ == "__main__":
    unittest.main()
