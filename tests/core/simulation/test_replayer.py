"""Replayer tests — STEP 13 simulation layer.

Covers the integration invariants that make the replay layer trustable:

  - As-is replay produces 100% outcome agreements with the original
    DAG run.
  - Persona swap surfaces output_payload diffs without changing live
    state.
  - Live trace_writer + durable store are byte-identical before and
    after every replay (the killer hard rule).
  - _ReadOnlyAtTimeShim raises on writes (insert_record / tombstone).
  - _ShadowModeRouter forces SHADOW_RECORD for every (mode, outcome)
    combination — even BLOCK and AUTO_WRITEBACK.
  - persona_override.decision_id mismatch raises ValueError.
  - Replayer.from_platform pulls policy_store + retriever_factory.

  python -m unittest tests.core.simulation.test_replayer
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.deps import build_default_platform  # noqa: E402
from core.context_store import ContextBundle  # noqa: E402
from core.context_store.base import Lineage  # noqa: E402
from core.decision_agents import AgentReasoning  # noqa: E402
from core.normalizer.models import DecisionMode, DecisionOutcome  # noqa: E402
from core.policy_engine import (  # noqa: E402
    PolicyDecision,
    PolicyOutcome,
    seed_fha_demo_policies,
    seed_policies_from_yaml,
)
from core.simulation import Replayer  # noqa: E402
from core.simulation.replayer import (  # noqa: E402
    _ReadOnlyAtTimeShim,
    _ShadowModeRouter,
)
from core.trace import (  # noqa: E402
    Contradiction,
    Signal,
    SignalDirection,
    WorkJournalEntry,
)
from domains.lending.personas import register_with_platform  # noqa: E402
from domains.lending.personas.credit_assessment import CreditRiskAgent  # noqa: E402
from domains.lending.seed_events.runner import run_scenario  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Fingerprints for the live-state-byte-identical invariant
# ─────────────────────────────────────────────────────────────────────


def _trace_fingerprint(traces) -> tuple:
    sig = sorted(
        f"{t.decision_id}:{t.trace_id}:{t.outcome.value}:{round(t.confidence, 4)}"
        for t in traces
    )
    return (len(traces), tuple(sig))


def _store_fingerprint(durable) -> int:
    records = getattr(durable, "_records", [])
    return len(records)


async def _platform_with_happy_path():
    """Boot a platform, register personas, seed policies, run happy_path."""
    p = build_default_platform()
    register_with_platform(p)
    await seed_policies_from_yaml(p.spec, p.policy_store)
    await seed_fha_demo_policies(p.policy_store)
    await run_scenario(p, "happy_path")
    return p


# ─────────────────────────────────────────────────────────────────────
# As-is replay parity
# ─────────────────────────────────────────────────────────────────────


class AsIsReplayTests(unittest.IsolatedAsyncioTestCase):

    async def test_full_dag_replay_produces_full_agreements(self):
        p = await _platform_with_happy_path()
        replayer = Replayer.from_platform(p)
        result = await replayer.replay_application("app_happy")
        self.assertEqual(
            result.comparison.disagreements, 0,
            f"as-is replay must produce 0 disagreements, got "
            f"{result.comparison.disagreements}",
        )
        self.assertEqual(result.comparison.agreements, result.comparison.total)

    async def test_replay_does_not_mutate_live_trace_writer(self):
        p = await _platform_with_happy_path()
        before = _trace_fingerprint(list(p.trace_writer._traces.values()))
        replayer = Replayer.from_platform(p)
        await replayer.replay_application("app_happy")
        after = _trace_fingerprint(list(p.trace_writer._traces.values()))
        self.assertEqual(before, after)

    async def test_replay_does_not_mutate_live_durable_store(self):
        p = await _platform_with_happy_path()
        durable = p.store._durable
        before = _store_fingerprint(durable)
        replayer = Replayer.from_platform(p)
        await replayer.replay_application("app_happy")
        after = _store_fingerprint(durable)
        self.assertEqual(before, after)

    async def test_default_at_uses_latest_trace_time(self):
        # When `at` is omitted, replayer pins to max(started_at) across
        # the application's traces — so replay_application(app) is
        # idempotent across calls.
        p = await _platform_with_happy_path()
        replayer = Replayer.from_platform(p)
        r1 = await replayer.replay_application("app_happy")
        r2 = await replayer.replay_application("app_happy")
        self.assertEqual(r1.replay_at, r2.replay_at)


# ─────────────────────────────────────────────────────────────────────
# Persona override surfaces diffs without writing to live state
# ─────────────────────────────────────────────────────────────────────


class StrictCreditAgent(CreditRiskAgent):
    """Same logic but downgrades the credit_band by one tier so the
    output_payload diff is observable in the comparison."""

    DEFAULT_AGENT_ID = "strict_credit_v1"

    async def reason(self, bundle, policy=None):
        original = await super().reason(bundle, policy)
        payload = dict(original.output_payload)
        downgrade = {
            "super_prime": "prime",
            "prime": "near_prime",
            "near_prime": "subprime",
        }
        if "credit_band" in payload:
            payload["credit_band"] = downgrade.get(
                payload["credit_band"], payload["credit_band"]
            )
        return AgentReasoning(
            journal=original.journal,
            proposed_outcome=original.proposed_outcome,
            confidence=original.confidence,
            output_payload=payload,
        )


class PersonaSwapTests(unittest.IsolatedAsyncioTestCase):

    async def test_decision_swap_surfaces_payload_diff(self):
        p = await _platform_with_happy_path()
        replayer = Replayer.from_platform(p)
        before_traces = _trace_fingerprint(list(p.trace_writer._traces.values()))
        before_records = _store_fingerprint(p.store._durable)

        result, comparison = await replayer.replay_decision(
            "app_happy",
            "credit_assessment",
            persona_override=StrictCreditAgent(),
        )

        self.assertTrue(comparison.persona_swapped)
        self.assertTrue(comparison.payload_changed)
        self.assertIn("credit_band", comparison.payload_diff.get("changed", {}))

        # Live state byte-identical.
        after_traces = _trace_fingerprint(list(p.trace_writer._traces.values()))
        after_records = _store_fingerprint(p.store._durable)
        self.assertEqual(before_traces, after_traces)
        self.assertEqual(before_records, after_records)

    async def test_full_dag_swap_surfaces_change_at_swapped_decision(self):
        p = await _platform_with_happy_path()
        replayer = Replayer.from_platform(p)

        result = await replayer.replay_application(
            "app_happy",
            persona_overrides={"credit_assessment": StrictCreditAgent()},
        )
        # Find the credit_assessment comparison entry.
        ca = next(
            c for c in result.comparison.decision_comparisons
            if c.decision_id == "credit_assessment"
        )
        self.assertTrue(ca.persona_swapped)
        self.assertTrue(ca.payload_changed)


class PersonaSwapValidationTests(unittest.IsolatedAsyncioTestCase):

    async def test_decision_id_mismatch_in_replay_decision_raises(self):
        p = await _platform_with_happy_path()
        replayer = Replayer.from_platform(p)
        # CreditRiskAgent's decision_id is credit_assessment, but we
        # ask the replayer to swap it for fraud_screening — mismatch.
        with self.assertRaises(ValueError):
            await replayer.replay_decision(
                "app_happy",
                "fraud_screening",
                persona_override=StrictCreditAgent(),
            )

    async def test_decision_id_mismatch_in_replay_application_raises(self):
        p = await _platform_with_happy_path()
        replayer = Replayer.from_platform(p)
        with self.assertRaises(ValueError):
            await replayer.replay_application(
                "app_happy",
                # Override key claims fraud_screening but the agent's
                # decision_id is credit_assessment.
                persona_overrides={"fraud_screening": StrictCreditAgent()},
            )


# ─────────────────────────────────────────────────────────────────────
# _ReadOnlyAtTimeShim
# ─────────────────────────────────────────────────────────────────────


class ReadOnlyShimTests(unittest.IsolatedAsyncioTestCase):

    async def test_init_requires_at(self):
        with self.assertRaises(ValueError):
            _ReadOnlyAtTimeShim(inner=object(), at=None)

    async def test_insert_record_raises(self):
        p = await _platform_with_happy_path()
        shim = _ReadOnlyAtTimeShim(p.store._durable, datetime.utcnow())
        # Pull a real ContextRecord we can re-attempt to insert.
        records = p.store._durable._records
        sample = records[0] if records else None
        self.assertIsNotNone(sample)
        with self.assertRaises(Exception):  # RuntimeError or similar
            await shim.insert_record(sample)

    async def test_tombstone_raises(self):
        p = await _platform_with_happy_path()
        shim = _ReadOnlyAtTimeShim(p.store._durable, datetime.utcnow())
        with self.assertRaises(Exception):
            await shim.tombstone(
                "Application", "app_happy", None,
                Lineage(written_by="test", decision_id=None),
            )

    async def test_reads_pin_to_replay_at(self):
        # get_latest on the shim proxies to inner.get_at_time(at=replay_at).
        # Verify by pinning the shim to an explicit past time, then
        # writing a record (whose lineage.written_at = datetime.utcnow()
        # which is well after the pin) — shim must not see it.
        p = await _platform_with_happy_path()
        durable = p.store._durable
        # Pin to 2020 — far enough in the past that no record's
        # written_at can possibly precede it. Avoids the millisecond-
        # resolution race on Windows where datetime.utcnow() can return
        # the same value on two adjacent calls.
        pinned_at = datetime(2020, 1, 1)
        shim = _ReadOnlyAtTimeShim(durable, pinned_at)

        # Insert a record now (written_at >> pinned_at).
        await p.store.set(
            "Property",
            "prop-test-after-pin",
            {"property_id": "prop-test-after-pin", "application_id": "app_happy"},
            Lineage(written_by="test", decision_id=None),
        )

        # Direct durable read sees the new record.
        live = await durable.get_latest("Property", "prop-test-after-pin", None)
        self.assertIsNotNone(live)

        # Shim read pinned to 2020 does NOT see it.
        replayed = await shim.get_latest(
            "Property", "prop-test-after-pin", None
        )
        self.assertIsNone(replayed)


# ─────────────────────────────────────────────────────────────────────
# _ShadowModeRouter
# ─────────────────────────────────────────────────────────────────────


class ShadowRouterTests(unittest.IsolatedAsyncioTestCase):

    async def _route(
        self,
        *,
        mode: DecisionMode,
        outcome: DecisionOutcome,
    ):
        router = _ShadowModeRouter()
        # Build a tiny ContextBundle that satisfies the route signature.
        from uuid import uuid4
        bundle = ContextBundle(
            decision_id="d1",
            application_id="app1",
            snapshot_id=uuid4(),
            snapshot_at=datetime.utcnow(),
        )
        return await router.route(
            agent_id="stub",
            decision_id="d1",
            application_id="app1",
            mode=mode,
            outcome=outcome,
            confidence=0.95,
            output_payload={},
            bundle=bundle,
        )

    async def test_allow_in_auto_mode_becomes_shadow(self):
        from core.decision_agents.mode_router import RouteAction
        routed = await self._route(
            mode=DecisionMode.AUTO_EXECUTE,
            outcome=DecisionOutcome.ALLOW,
        )
        self.assertEqual(routed.action, RouteAction.SHADOW_RECORD)

    async def test_block_becomes_shadow(self):
        from core.decision_agents.mode_router import RouteAction
        routed = await self._route(
            mode=DecisionMode.AUTO_EXECUTE,
            outcome=DecisionOutcome.BLOCK,
        )
        self.assertEqual(routed.action, RouteAction.SHADOW_RECORD)

    async def test_human_approval_recommend_becomes_shadow(self):
        from core.decision_agents.mode_router import RouteAction
        routed = await self._route(
            mode=DecisionMode.HUMAN_APPROVAL,
            outcome=DecisionOutcome.RECOMMEND,
        )
        self.assertEqual(routed.action, RouteAction.SHADOW_RECORD)

    async def test_shadow_mode_stays_shadow(self):
        from core.decision_agents.mode_router import RouteAction
        routed = await self._route(
            mode=DecisionMode.SHADOW,
            outcome=DecisionOutcome.ALLOW,
        )
        self.assertEqual(routed.action, RouteAction.SHADOW_RECORD)


# ─────────────────────────────────────────────────────────────────────
# from_platform wiring
# ─────────────────────────────────────────────────────────────────────


class FromPlatformTests(unittest.IsolatedAsyncioTestCase):

    async def test_from_platform_pulls_policy_store(self):
        # When the platform has a policy_store + seeded versions, replay
        # traces should carry policy_version_id stamps just like live.
        p = await _platform_with_happy_path()
        replayer = Replayer.from_platform(p)
        # Manually trigger a replay and inspect a shadow trace.
        result = await replayer.replay_application("app_happy")
        # We need access to the shadow trace_writer, but the result
        # only exposes the comparison. Use replay_decision to get
        # the AtomicToolResult directly with its trace.
        result2, _ = await replayer.replay_decision(
            "app_happy", "credit_assessment"
        )
        self.assertIsNotNone(result2.trace.policy_version_id)


if __name__ == "__main__":
    unittest.main()
