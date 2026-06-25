"""Unit tests for CI-B historical decision replay (read-only).

Covers replay_decision + replay_all_decisions against a fake asyncpg conn that
serves decision_outputs / persona_bundles / entity_states / tenant_rules (per
version) / agency_guidelines. Encodes the real meridian shapes: a sole-constraint
cross-version flip, the shadow-safe "already blocked by another persona" case, and
a NULL field (RULE 11).

The eval timeout guard (asyncio.wait_for in scripts/evaluate_meridian_scenarios.py)
is verified functionally — that module runs asyncio.run at import (ARCHITECTURE:
"DO NOT IMPORT"), so it is not unit-tested here.
"""
import asyncio
import unittest
from datetime import datetime

from core.intelligence.decision_replay import replay_decision, replay_all_decisions

V1 = "11111111-1111-1111-1111-111111111111"
V2 = "22222222-2222-2222-2222-222222222222"

# v1: dti cap 43, credit floor 640; v2: dti cap 40 (stricter), credit floor 680
VERSION_RULES = {
    V1: {"credit": {"min_score": 640}, "dti": {"back_max": 43}, "ltv": {"max": 97}},
    V2: {"credit": {"min_score": 680}, "dti": {"back_max": 40}, "ltv": {"max": 97}},
}


class _FakeConn:
    def __init__(self, decision=None, bundle=None, entity=None, apps=None):
        self.decision = decision
        self.bundle = bundle
        self.entity = entity
        self.apps = apps or []

    async def fetchrow(self, q, *a):
        if "FROM decision_outputs" in q and "DISTINCT ON (application_id)" in q:
            return self.decision
        if "persona_bundles" in q:
            return self.bundle
        if "FROM entity_states" in q:
            return self.entity
        if "FROM tenant_rules" in q:
            rid = str(a[0]) if a else None
            rules = VERSION_RULES.get(rid)
            return {"rules": rules} if rules is not None else None
        return None

    async def fetch(self, q, *a):
        if "agency_guidelines" in q:
            return []
        if "FROM decision_outputs" in q and "DISTINCT application_id" in q:
            return self.apps
        return []


def _decision(app, outcome, version=V1):
    return {"application_id": app, "outcome": outcome, "rule_version_id": version,
            "created_at": datetime(2026, 1, 1)}


def _bundle(upstream):
    return {"upstream_snapshot": {k: {"outcome": v} for k, v in upstream.items()}}


def _entity(score=720, dti=42.0, ltv=85.0, amt=374000.0):
    return {"mid_credit_score": score, "dti_back": dti, "ltv": ltv, "loan_amount": amt}


def _run(coro):
    return asyncio.run(coro)


class ReplayDecisionTests(unittest.TestCase):
    def test_cross_version_flip_recommend_to_block(self):
        # recommend app, sole-clean; dti 42 passes v1 (<=43) but fails v2 (<=40)
        conn = _FakeConn(
            decision=_decision("SC16", "recommend"),
            bundle=_bundle({"credit_assessment": "allow", "dti_calculation": "recommend",
                            "ltv_assessment": "recommend", "product_eligibility": "allow",
                            "fraud_screening": "allow", "income_verification": "recommend"}),
            entity=_entity(score=729, dti=42.0, ltv=85.0))
        r = _run(replay_decision(conn, "SC16", "meridian", V2))
        self.assertTrue(r["success"])
        self.assertTrue(r["diff"]["outcome_changed"])
        self.assertEqual(r["diff"]["replayed_outcome"], "block")
        self.assertTrue(r["replay_fidelity_ok"])
        # the dti gate is the one that flipped
        flipped = [g["persona"] for g in r["diff"]["gate_changes"]]
        self.assertIn("dti_calculation", flipped)

    def test_shadowed_already_blocked_stays_block(self):
        # block app: dti gate clears under looser? no — here credit clears but
        # product_eligibility still blocks -> stays block (no false flip)
        conn = _FakeConn(
            decision=_decision("SC01", "block"),
            bundle=_bundle({"credit_assessment": "block", "dti_calculation": "recommend",
                            "product_eligibility": "block", "fraud_screening": "allow",
                            "ltv_assessment": "recommend", "income_verification": "recommend"}),
            entity=_entity(score=650, dti=30.0, ltv=85.0))
        # target == v1 here (credit 640): score 650 passes both -> no gate change anyway
        r = _run(replay_decision(conn, "SC01", "meridian", V1))
        self.assertFalse(r["diff"]["outcome_changed"])
        self.assertEqual(r["diff"]["replayed_outcome"], "block")

    def test_shadowed_gate_clears_but_other_persona_blocks(self):
        # credit gate would clear at a looser version, but product_eligibility blocks
        conn = _FakeConn(
            decision=_decision("X", "block", version=V2),  # original under v2 (credit 680)
            bundle=_bundle({"credit_assessment": "block", "dti_calculation": "recommend",
                            "product_eligibility": "block", "fraud_screening": "allow",
                            "ltv_assessment": "recommend", "income_verification": "recommend"}),
            entity=_entity(score=660, dti=30.0, ltv=85.0))
        # replay under v1 (credit 640): score 660 fails v2 (680) but passes v1 (640)
        # -> credit gate clears, BUT product_eligibility=block -> still block
        r = _run(replay_decision(conn, "X", "meridian", V1))
        self.assertFalse(r["diff"]["outcome_changed"])
        self.assertEqual(r["diff"]["replayed_outcome"], "block")
        self.assertTrue(any(g["persona"] == "credit_assessment" for g in r["diff"]["gate_changes"]))

    def test_null_field_missing_inputs_rule11(self):
        conn = _FakeConn(
            decision=_decision("SC03", "block"),
            bundle=_bundle({"dti_calculation": "block", "product_eligibility": "block"}),
            entity=_entity(dti=None))
        r = _run(replay_decision(conn, "SC03", "meridian", V2))
        self.assertTrue(any("dti_back" in m for m in r["missing_inputs"]))

    def test_no_decision_errors(self):
        r = _run(replay_decision(_FakeConn(decision=None), "Z", "meridian", V2))
        self.assertFalse(r["success"])
        self.assertIn("missing_inputs", r)

    def test_no_bundle_errors(self):
        r = _run(replay_decision(
            _FakeConn(decision=_decision("Z", "block"), bundle=None), "Z", "meridian", V2))
        self.assertFalse(r["success"])
        self.assertIn("persona_bundles", r["data_source"])

    def test_provenance_and_caveat_present(self):
        conn = _FakeConn(
            decision=_decision("A", "recommend"),
            bundle=_bundle({"dti_calculation": "recommend", "credit_assessment": "allow"}),
            entity=_entity(dti=42.0))
        r = _run(replay_decision(conn, "A", "meridian", V2))
        self.assertIn("data_source", r)
        self.assertIn("honest_caveat", r)
        self.assertIn("threshold_changes", r["diff"])


class ReplayAllTests(unittest.TestCase):
    def test_bulk_counts_changed(self):
        # one app flips (dti 42 -> block under v2), one stays (already block)
        class _MultiConn(_FakeConn):
            async def fetchrow(self, q, *a):
                if "FROM decision_outputs" in q and "DISTINCT ON" in q:
                    app = a[0]
                    return _decision(app, "recommend" if app == "FLIP" else "block")
                if "persona_bundles" in q:
                    app = a[0]
                    if app == "FLIP":
                        return _bundle({"dti_calculation": "recommend", "credit_assessment": "allow",
                                        "product_eligibility": "allow"})
                    return _bundle({"dti_calculation": "recommend", "product_eligibility": "block"})
                if "FROM entity_states" in q:
                    return _entity(dti=42.0)
                if "FROM tenant_rules" in q:
                    rid = str(a[0]) if a else None
                    return {"rules": VERSION_RULES.get(rid)}
                return None

        conn = _MultiConn(apps=[{"application_id": "FLIP"}, {"application_id": "STAY"}])
        r = _run(replay_all_decisions(conn, "meridian", V2))
        self.assertEqual(r["total_replayed"], 2)
        self.assertEqual(r["outcomes_changed"], 1)
        self.assertEqual(r["changed_decisions"][0]["application_id"], "FLIP")
        self.assertEqual(r["fidelity_failures"], 0)


if __name__ == "__main__":
    unittest.main()
