"""PolicyEvaluator tests — async path with PolicyStore + version stamps.

Covers:
  - Hard-rule short-circuits (fraud_block, compliance_block_stops_closing,
    upstream_block_propagates_to_dependents) all carry the version stamp
    when policy_store is wired.
  - contamination_guard with reject_if_upstream_confidence_below blocks
    + flags contamination=True.
  - Boundary clause priority: block > escalate > recommend > automate.
  - No-clause-match falls back to ESCALATE (safe default).
  - With policy_store: outcome reads from the seeded version's boundary;
    policy_version_id and policy_chain are stamped.
  - Without policy_store: legacy YAML path; policy_version_id is None.
  - agency_chain ordering — overlay-first precedence; chain captures
    every consulted agency that has an active version.

  python -m unittest tests.core.policy_engine.test_evaluator
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.context_store import (  # noqa: E402
    InMemoryDurableStore,
    InMemoryHotCache,
    LendingContextStore,
)
from core.policy_engine import (  # noqa: E402
    PolicyEvaluator,
    PolicyOutcome,
    PolicyRecord,
    PolicyStore,
    PolicyVersionRecord,
    UpstreamSummary,
)


def _spec_with_decisions(*decision_overrides) -> dict:
    """Build a small spec with the decisions we need for the test."""
    decisions = []
    for d in decision_overrides:
        merged = {
            "id": d["id"],
            "name": d.get("name", d["id"]),
            "owner_team": "ops",
            "mode": "auto_execute",
            "risk_level": "medium",
            "boundary": {},
        }
        merged.update(d)
        decisions.append(merged)
    return {
        "domain": "test",
        "version": "0.1.0",
        "decisions": decisions,
    }


def _store_pair() -> tuple[LendingContextStore, PolicyStore]:
    backing = LendingContextStore(InMemoryHotCache(), InMemoryDurableStore())
    return backing, PolicyStore(backing)


async def _seed_version(
    store: PolicyStore,
    *,
    decision_id: str,
    agency: str = "lender_overlay",
    boundary: dict | None = None,
    contamination_guard: dict | None = None,
):
    policy_id = f"{agency}::{decision_id}"
    version_id = f"{policy_id}::v1"
    await store.put_policy(PolicyRecord(
        policy_id=policy_id,
        name="seeded",
        owner_team="ops",
        agency=agency,
        decision_id=decision_id,
    ))
    await store.put_policy_version(PolicyVersionRecord(
        policy_version_id=version_id,
        policy_id=policy_id,
        version_number=1,
        valid_from=datetime(2020, 1, 1),
        boundary=boundary or {"automate_if": ["score >= 0.5"]},
        contamination_guard=contamination_guard,
        ingested_at=datetime(2026, 1, 1),
    ))
    return version_id


# ─────────────────────────────────────────────────────────────────────
# Boundary priority + default escalate
# ─────────────────────────────────────────────────────────────────────


class BoundaryPriorityTests(unittest.IsolatedAsyncioTestCase):

    async def test_automate_clause_matches(self):
        spec = _spec_with_decisions({
            "id": "d1",
            "boundary": {"automate_if": ["score >= 0.5"]},
        })
        evaluator = PolicyEvaluator(spec)
        result = await evaluator.evaluate("d1", {"score": 0.9})
        self.assertEqual(result.outcome, PolicyOutcome.ALLOW)
        self.assertEqual(result.matched_clause, "automate_if")

    async def test_block_beats_automate(self):
        # Both block and automate clauses match — block wins.
        spec = _spec_with_decisions({
            "id": "d1",
            "boundary": {
                "automate_if": ["score >= 0.5"],
                "block_if":    ["score >= 0.5"],
            },
        })
        evaluator = PolicyEvaluator(spec)
        result = await evaluator.evaluate("d1", {"score": 0.9})
        self.assertEqual(result.outcome, PolicyOutcome.BLOCK)
        self.assertEqual(result.matched_clause, "block_if")

    async def test_escalate_beats_recommend_beats_automate(self):
        spec = _spec_with_decisions({
            "id": "d1",
            "boundary": {
                "automate_if":  ["score >= 0.0"],
                "recommend_if": ["score >= 0.5"],
                "escalate_if":  ["score >= 0.7"],
            },
        })
        evaluator = PolicyEvaluator(spec)
        # All three match for score=0.9 — escalate wins.
        result = await evaluator.evaluate("d1", {"score": 0.9})
        self.assertEqual(result.outcome, PolicyOutcome.ESCALATE)

    async def test_no_clause_matches_falls_back_to_escalate(self):
        spec = _spec_with_decisions({
            "id": "d1",
            "boundary": {"automate_if": ["score >= 0.99"]},
        })
        evaluator = PolicyEvaluator(spec)
        result = await evaluator.evaluate("d1", {"score": 0.5})
        self.assertEqual(result.outcome, PolicyOutcome.ESCALATE)
        self.assertIsNone(result.matched_clause)
        self.assertIn("safe default", " ".join(result.reasons))


# ─────────────────────────────────────────────────────────────────────
# Hard-rule short-circuits
# ─────────────────────────────────────────────────────────────────────


class HardRuleTests(unittest.IsolatedAsyncioTestCase):

    async def test_fraud_block_propagates_to_downstream(self):
        spec = _spec_with_decisions({
            "id": "ltv_assessment",
            "boundary": {"automate_if": ["ltv <= 0.95"]},
        })
        evaluator = PolicyEvaluator(spec)
        result = await evaluator.evaluate(
            "ltv_assessment",
            {"ltv": 0.5},
            upstream=[
                UpstreamSummary(
                    decision_id="fraud_screening",
                    outcome=PolicyOutcome.BLOCK,
                    confidence=0.95,
                ),
            ],
        )
        self.assertEqual(result.outcome, PolicyOutcome.BLOCK)
        self.assertIn("fraud_block_stops_pipeline", " ".join(result.reasons))

    async def test_compliance_block_stops_closing(self):
        spec = _spec_with_decisions({
            "id": "closing_readiness",
            "boundary": {"automate_if": ["title_clear == true"]},
        })
        evaluator = PolicyEvaluator(spec)
        result = await evaluator.evaluate(
            "closing_readiness",
            {"title_clear": True},
            upstream=[
                UpstreamSummary(
                    decision_id="compliance_check",
                    outcome=PolicyOutcome.BLOCK,
                ),
            ],
        )
        self.assertEqual(result.outcome, PolicyOutcome.BLOCK)
        self.assertIn("compliance_block_stops_closing", " ".join(result.reasons))

    async def test_upstream_block_propagates_to_dependent(self):
        spec = _spec_with_decisions({
            "id": "dti_calculation",
            "boundary": {"automate_if": ["dti <= 0.36"]},
        })
        evaluator = PolicyEvaluator(spec)
        result = await evaluator.evaluate(
            "dti_calculation",
            {"dti": 0.30},
            upstream=[
                UpstreamSummary(
                    decision_id="income_verification",
                    outcome=PolicyOutcome.BLOCK,
                ),
            ],
        )
        self.assertEqual(result.outcome, PolicyOutcome.BLOCK)
        self.assertIn(
            "upstream_block_propagates_to_dependents",
            " ".join(result.reasons),
        )


# ─────────────────────────────────────────────────────────────────────
# contamination_guard
# ─────────────────────────────────────────────────────────────────────


class ContaminationGuardTests(unittest.IsolatedAsyncioTestCase):

    async def test_reject_if_upstream_confidence_below_threshold(self):
        spec = _spec_with_decisions({
            "id": "dti_calculation",
            "boundary": {"automate_if": ["dti <= 0.36"]},
            "contamination_guard": {"reject_if_upstream_confidence_below": 0.75},
        })
        evaluator = PolicyEvaluator(spec)
        result = await evaluator.evaluate(
            "dti_calculation",
            {"dti": 0.30},
            upstream=[
                UpstreamSummary(
                    decision_id="income_verification",
                    outcome=PolicyOutcome.RECOMMEND,
                    confidence=0.50,  # below 0.75
                ),
            ],
        )
        self.assertEqual(result.outcome, PolicyOutcome.BLOCK)
        self.assertTrue(result.contamination)
        self.assertIn("contamination_guard threshold", " ".join(result.reasons))

    async def test_threshold_not_violated_passes(self):
        spec = _spec_with_decisions({
            "id": "dti_calculation",
            "boundary": {"automate_if": ["dti <= 0.36"]},
            "contamination_guard": {"reject_if_upstream_confidence_below": 0.75},
        })
        evaluator = PolicyEvaluator(spec)
        result = await evaluator.evaluate(
            "dti_calculation",
            {"dti": 0.30},
            upstream=[
                UpstreamSummary(
                    decision_id="income_verification",
                    outcome=PolicyOutcome.ALLOW,
                    confidence=0.95,  # above 0.75
                ),
            ],
        )
        self.assertEqual(result.outcome, PolicyOutcome.ALLOW)
        self.assertFalse(result.contamination)

    async def test_fail_if_any_upstream_blocked(self):
        spec = _spec_with_decisions({
            "id": "underwriting_decision",
            "boundary": {"automate_if": ["risk_score <= 0.25"]},
            "contamination_guard": {"fail_if_any_upstream_blocked": True},
        })
        evaluator = PolicyEvaluator(spec)
        # The fraud_block_stops_pipeline rule actually catches BLOCK
        # upstreams first — to test fail_if_any_upstream_blocked
        # specifically, use a non-fraud non-compliance upstream.
        # Actually any BLOCK upstream falls into the generic
        # upstream_block_propagates check first, so this guard
        # path is more of a defense-in-depth for cases where the
        # generic check doesn't fire (today: never). Test it anyway
        # to lock the behavior.
        # Use a custom decision_id so the generic propagate check
        # still applies — both should produce BLOCK.
        result = await evaluator.evaluate(
            "underwriting_decision",
            {"risk_score": 0.10},
            upstream=[
                UpstreamSummary(
                    decision_id="dti_calculation",
                    outcome=PolicyOutcome.BLOCK,
                ),
            ],
        )
        self.assertEqual(result.outcome, PolicyOutcome.BLOCK)


# ─────────────────────────────────────────────────────────────────────
# PolicyStore integration: version stamping
# ─────────────────────────────────────────────────────────────────────


class PolicyStoreIntegrationTests(unittest.IsolatedAsyncioTestCase):

    async def test_legacy_path_no_policy_store_no_stamp(self):
        spec = _spec_with_decisions({
            "id": "d1",
            "boundary": {"automate_if": ["score >= 0.5"]},
        })
        evaluator = PolicyEvaluator(spec)
        result = await evaluator.evaluate("d1", {"score": 0.9})
        self.assertEqual(result.outcome, PolicyOutcome.ALLOW)
        self.assertIsNone(result.policy_version_id)
        self.assertEqual(result.policy_chain, [])

    async def test_with_policy_store_stamps_version_id(self):
        spec = _spec_with_decisions({
            "id": "d1",
            "boundary": {"automate_if": ["score >= 0.99"]},  # YAML — won't match
        })
        backing, store = _store_pair()
        # Seed a different boundary in the store; that wins because
        # the store is wired.
        version_id = await _seed_version(
            store,
            decision_id="d1",
            boundary={"automate_if": ["score >= 0.5"]},
        )
        evaluator = PolicyEvaluator(spec)
        result = await evaluator.evaluate(
            "d1",
            {"score": 0.9},
            policy_store=store,
            agency_chain=["lender_overlay"],
        )
        self.assertEqual(result.outcome, PolicyOutcome.ALLOW)
        self.assertEqual(result.policy_version_id, version_id)
        self.assertEqual(result.policy_chain, [version_id])

    async def test_hard_rule_short_circuit_carries_stamp(self):
        spec = _spec_with_decisions({
            "id": "ltv_assessment",
            "boundary": {"automate_if": ["ltv <= 0.95"]},
        })
        backing, store = _store_pair()
        version_id = await _seed_version(
            store,
            decision_id="ltv_assessment",
            boundary={"automate_if": ["ltv <= 0.95"]},
        )
        evaluator = PolicyEvaluator(spec)
        result = await evaluator.evaluate(
            "ltv_assessment",
            {"ltv": 0.5},
            upstream=[
                UpstreamSummary(
                    decision_id="fraud_screening",
                    outcome=PolicyOutcome.BLOCK,
                ),
            ],
            policy_store=store,
            agency_chain=["lender_overlay"],
        )
        # Outcome is BLOCK from fraud_block_stops_pipeline, AND it
        # still carries the policy_version_id stamp.
        self.assertEqual(result.outcome, PolicyOutcome.BLOCK)
        self.assertEqual(result.policy_version_id, version_id)

    async def test_contamination_guard_carries_stamp(self):
        spec = _spec_with_decisions({
            "id": "dti_calculation",
            "boundary": {"automate_if": ["dti <= 0.36"]},
        })
        backing, store = _store_pair()
        version_id = await _seed_version(
            store,
            decision_id="dti_calculation",
            boundary={"automate_if": ["dti <= 0.36"]},
            contamination_guard={"reject_if_upstream_confidence_below": 0.75},
        )
        evaluator = PolicyEvaluator(spec)
        result = await evaluator.evaluate(
            "dti_calculation",
            {"dti": 0.30},
            upstream=[
                UpstreamSummary(
                    decision_id="income_verification",
                    outcome=PolicyOutcome.RECOMMEND,
                    confidence=0.50,
                ),
            ],
            policy_store=store,
            agency_chain=["lender_overlay"],
        )
        self.assertEqual(result.outcome, PolicyOutcome.BLOCK)
        self.assertTrue(result.contamination)
        self.assertEqual(result.policy_version_id, version_id)


class AgencyChainTests(unittest.IsolatedAsyncioTestCase):

    async def test_chain_captures_every_consulted_agency_with_active_version(self):
        spec = _spec_with_decisions({
            "id": "ltv_assessment",
            "boundary": {"automate_if": ["ltv <= 0.95"]},
        })
        backing, store = _store_pair()
        overlay_id = await _seed_version(
            store,
            decision_id="ltv_assessment",
            agency="lender_overlay",
            boundary={"automate_if": ["ltv <= 0.97"]},
        )
        fha_id = await _seed_version(
            store,
            decision_id="ltv_assessment",
            agency="fha",
            boundary={"automate_if": ["ltv <= 0.965"]},
        )
        evaluator = PolicyEvaluator(spec)
        result = await evaluator.evaluate(
            "ltv_assessment",
            {"ltv": 0.5},
            policy_store=store,
            agency_chain=["lender_overlay", "fha"],
        )
        self.assertEqual(result.outcome, PolicyOutcome.ALLOW)
        # Overlay-first → overlay's version is the chosen one.
        self.assertEqual(result.policy_version_id, overlay_id)
        # Chain captures both consulted versions in chain order.
        self.assertEqual(result.policy_chain, [overlay_id, fha_id])

    async def test_missing_agency_omitted_from_chain(self):
        spec = _spec_with_decisions({
            "id": "ltv_assessment",
            "boundary": {"automate_if": ["ltv <= 0.95"]},
        })
        backing, store = _store_pair()
        overlay_id = await _seed_version(
            store,
            decision_id="ltv_assessment",
            agency="lender_overlay",
        )
        # No fha version seeded — chain should reflect that.
        evaluator = PolicyEvaluator(spec)
        result = await evaluator.evaluate(
            "ltv_assessment",
            {"ltv": 0.5},
            policy_store=store,
            agency_chain=["lender_overlay", "fha"],
        )
        self.assertEqual(result.policy_chain, [overlay_id])

    async def test_no_active_versions_falls_back_to_yaml(self):
        spec = _spec_with_decisions({
            "id": "d1",
            "boundary": {"automate_if": ["score >= 0.5"]},
        })
        backing, store = _store_pair()
        # Empty store — chain finds nothing → falls back to YAML.
        evaluator = PolicyEvaluator(spec)
        result = await evaluator.evaluate(
            "d1",
            {"score": 0.9},
            policy_store=store,
            agency_chain=["lender_overlay"],
        )
        self.assertEqual(result.outcome, PolicyOutcome.ALLOW)
        self.assertIsNone(result.policy_version_id)
        self.assertEqual(result.policy_chain, [])


if __name__ == "__main__":
    unittest.main()
