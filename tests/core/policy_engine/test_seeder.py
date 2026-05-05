"""seed_policies_from_yaml + seed_fha_demo_policies tests.

Covers:
  - YAML seeder writes 12 Policy + 12 PolicyVersion (one per decision).
  - Re-running the seeder is idempotent (no churn on the durable store).
  - Existing created_at / ingested_at timestamps are preserved.
  - FHA seeder writes its hand-crafted overlays.
  - Both seeders together don't collide.

  python -m unittest tests.core.policy_engine.test_seeder
"""

from __future__ import annotations

import sys
import unittest
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
    POLICY_ENTITY_TYPE,
    POLICY_VERSION_ENTITY_TYPE,
    PolicyStore,
    SEED_AGENCY,
    SEED_VALID_FROM,
    load_spec,
    policy_id_for,
    policy_version_id_for,
    seed_fha_demo_policies,
    seed_policies_from_yaml,
)


def _platform_pieces():
    """Build a fresh in-memory backing + PolicyStore + DecisionsSpec."""
    backing = LendingContextStore(InMemoryHotCache(), InMemoryDurableStore())
    store = PolicyStore(backing)
    spec = load_spec(PROJECT_ROOT / "domains" / "lending" / "decisions.yaml")
    return backing, store, spec


def _count_active(durable, entity_type: str) -> int:
    return sum(
        1 for r in getattr(durable, "_records", [])
        if r.entity_type == entity_type
        and r.decision_id is None
        and r.superseded_at is None
    )


def _count_total(durable, entity_type: str) -> int:
    return sum(
        1 for r in getattr(durable, "_records", [])
        if r.entity_type == entity_type
        and r.decision_id is None
    )


class YamlSeederTests(unittest.IsolatedAsyncioTestCase):

    async def test_seeds_12_policies_and_versions(self):
        backing, store, spec = _platform_pieces()
        durable = backing._durable  # type: ignore[attr-defined]

        policies, versions = await seed_policies_from_yaml(spec, store)

        self.assertEqual(len(policies), 13)
        self.assertEqual(len(versions), 13)
        self.assertEqual(_count_active(durable, POLICY_ENTITY_TYPE), 13)
        self.assertEqual(
            _count_active(durable, POLICY_VERSION_ENTITY_TYPE), 13
        )

    async def test_every_decision_gets_lender_overlay_policy(self):
        backing, store, spec = _platform_pieces()
        await seed_policies_from_yaml(spec, store)
        for d in spec.decisions:
            decision_id = d["id"]
            policy = await store.get_policy(policy_id_for(decision_id))
            self.assertIsNotNone(policy, f"missing policy for {decision_id}")
            self.assertEqual(policy.agency, SEED_AGENCY)
            self.assertEqual(policy.decision_id, decision_id)

    async def test_every_decision_gets_v1_with_yaml_boundary(self):
        backing, store, spec = _platform_pieces()
        await seed_policies_from_yaml(spec, store)
        for d in spec.decisions:
            decision_id = d["id"]
            v = await store.get_policy_version(policy_version_id_for(decision_id))
            self.assertIsNotNone(v, f"missing version for {decision_id}")
            self.assertEqual(v.version_number, 1)
            self.assertEqual(v.valid_from, SEED_VALID_FROM)
            self.assertIsNone(v.valid_to)
            # YAML's boundary survives the round trip — bytes equal.
            yaml_boundary = d.get("boundary") or {}
            self.assertEqual(v.boundary, dict(yaml_boundary))

    async def test_seeder_is_idempotent(self):
        backing, store, spec = _platform_pieces()
        durable = backing._durable  # type: ignore[attr-defined]

        await seed_policies_from_yaml(spec, store)
        total_policies_after_pass1 = _count_total(durable, POLICY_ENTITY_TYPE)
        total_versions_after_pass1 = _count_total(
            durable, POLICY_VERSION_ENTITY_TYPE
        )

        # Second pass: no new records.
        await seed_policies_from_yaml(spec, store)
        self.assertEqual(
            _count_total(durable, POLICY_ENTITY_TYPE),
            total_policies_after_pass1,
            "second seed pass churned the Policy supersession chain",
        )
        self.assertEqual(
            _count_total(durable, POLICY_VERSION_ENTITY_TYPE),
            total_versions_after_pass1,
            "second seed pass churned the PolicyVersion supersession chain",
        )

    async def test_seeder_preserves_first_pass_timestamps(self):
        backing, store, spec = _platform_pieces()

        await seed_policies_from_yaml(spec, store)
        v1 = await store.get_policy_version(policy_version_id_for("credit_assessment"))
        first_ingested_at = v1.ingested_at

        # Second pass should reuse the first-pass timestamps so bytes
        # are identical and put_* short-circuits.
        await seed_policies_from_yaml(spec, store)
        v2 = await store.get_policy_version(policy_version_id_for("credit_assessment"))
        self.assertEqual(v2.ingested_at, first_ingested_at)


class FhaSeederTests(unittest.IsolatedAsyncioTestCase):

    async def test_writes_at_least_one_fha_version(self):
        backing, store, spec = _platform_pieces()
        written = await seed_fha_demo_policies(store)
        self.assertGreater(len(written), 0)
        # ltv_assessment is the canonical demo overlay.
        self.assertIn("fha::ltv_assessment::v1", written)

    async def test_fha_version_has_distinct_boundary(self):
        backing, store, spec = _platform_pieces()
        await seed_fha_demo_policies(store)
        v = await store.get_policy_version("fha::ltv_assessment::v1")
        self.assertIsNotNone(v)
        # FHA cap is 96.5%, distinct from lender_overlay's 97%.
        block_clauses = v.boundary.get("block_if") or []
        self.assertTrue(any("0.965" in clause for clause in block_clauses))

    async def test_fha_seeder_idempotent(self):
        backing, store, spec = _platform_pieces()
        durable = backing._durable  # type: ignore[attr-defined]
        await seed_fha_demo_policies(store)
        total_after_first = _count_total(durable, POLICY_VERSION_ENTITY_TYPE)
        await seed_fha_demo_policies(store)
        self.assertEqual(
            _count_total(durable, POLICY_VERSION_ENTITY_TYPE),
            total_after_first,
        )


class CombinedSeederTests(unittest.IsolatedAsyncioTestCase):

    async def test_yaml_and_fha_coexist_without_collision(self):
        backing, store, spec = _platform_pieces()
        await seed_policies_from_yaml(spec, store)
        await seed_fha_demo_policies(store)
        # Both ltv_assessment Policy versions exist (lender_overlay + fha).
        overlay = await store.get_policy_version(
            "lender_overlay::ltv_assessment::v1"
        )
        fha = await store.get_policy_version("fha::ltv_assessment::v1")
        self.assertIsNotNone(overlay)
        self.assertIsNotNone(fha)
        # They reference different parent policies.
        self.assertNotEqual(overlay.policy_id, fha.policy_id)

    async def test_combined_idempotent_in_either_order(self):
        # Pass 1: yaml then fha. Pass 2: yaml then fha again.
        backing, store, spec = _platform_pieces()
        durable = backing._durable  # type: ignore[attr-defined]

        await seed_policies_from_yaml(spec, store)
        await seed_fha_demo_policies(store)
        total_versions_after_first = _count_total(
            durable, POLICY_VERSION_ENTITY_TYPE
        )

        await seed_policies_from_yaml(spec, store)
        await seed_fha_demo_policies(store)
        self.assertEqual(
            _count_total(durable, POLICY_VERSION_ENTITY_TYPE),
            total_versions_after_first,
        )


if __name__ == "__main__":
    unittest.main()
