"""End-to-end exercise of the context_store in-memory backends.

Runs without pytest — uses unittest.IsolatedAsyncioTestCase so it works
on a fresh checkout with stdlib only. When pytest is added to
requirements.txt later, these classes will be picked up by pytest too.

  python -m unittest tests.core.context_store.test_in_memory
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Allow running from the repo root without installing the package.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.context_store import (  # noqa: E402
    ContextBuilder,
    ContextBundle,
    DECISION_TTL_SECONDS,
    InMemoryDurableStore,
    InMemoryHotCache,
    LendingContextStore,
    Lineage,
)
from core.ontology import LENDING_OBJECT_TYPES  # noqa: E402


def _shared_lineage(written_by: str = "ingest", confidence: float = 1.0) -> Lineage:
    return Lineage(written_by=written_by, decision_id=None, confidence=confidence)


class ContextStoreInMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.hot = InMemoryHotCache()
        self.durable = InMemoryDurableStore()
        self.store = LendingContextStore(hot=self.hot, durable=self.durable)

    async def test_imports_and_registry(self) -> None:
        self.assertIn("lead_scoring", DECISION_TTL_SECONDS)
        self.assertIn("Applicant", LENDING_OBJECT_TYPES)

    async def test_versioning_and_supersession(self) -> None:
        v1 = await self.store.set(
            "CreditProfile", "cp-1",
            {"credit_score": 740, "credit_band": "prime"},
            _shared_lineage(),
        )
        v2 = await self.store.set(
            "CreditProfile", "cp-1",
            {"credit_score": 745, "credit_band": "prime"},
            _shared_lineage(),
        )
        self.assertEqual(v1.version, 1)
        self.assertEqual(v2.version, 2)

        history = await self.store.history("CreditProfile", "cp-1")
        self.assertEqual([r.version for r in history], [2, 1])
        self.assertIsNotNone(history[1].superseded_at)
        self.assertEqual(history[1].superseded_by, v2.id)

    async def test_hot_cache_hit_after_write(self) -> None:
        await self.store.set(
            "CreditProfile", "cp-1",
            {"credit_score": 745},
            _shared_lineage(),
        )
        cached = await self.hot.get("CreditProfile", "cp-1", None)
        self.assertIsNotNone(cached)
        self.assertEqual(cached.value["credit_score"], 745)

    async def test_snapshot_reads_shared_scope(self) -> None:
        await self.store.set(
            "CreditProfile", "cp-1",
            {"credit_score": 760, "credit_band": "super_prime"},
            _shared_lineage(),
        )
        snap = await self.store.snapshot(
            application_id="app-1",
            decision_id="credit_assessment",
            entity_keys=[("CreditProfile", "cp-1")],
        )
        self.assertEqual(snap.context["CreditProfile"]["cp-1"]["credit_score"], 760)
        self.assertIn(snap.id.hex, [s.id.hex for s in self.durable._snapshots])

    async def test_tombstone_blocks_active_reads(self) -> None:
        await self.store.set(
            "CreditProfile", "cp-1",
            {"credit_score": 740},
            _shared_lineage(),
        )
        n = await self.store.delete(
            "CreditProfile", "cp-1", None,
            Lineage(written_by="ops_admin", decision_id=None, notes="tombstone"),
        )
        self.assertEqual(n, 1)

        latest = await self.store.get("CreditProfile", "cp-1")
        self.assertIsNone(latest)

        # Hot cache should also be invalidated.
        cached = await self.hot.get("CreditProfile", "cp-1", None)
        self.assertIsNone(cached)

        # Full history is preserved (append-only).
        history = await self.store.history("CreditProfile", "cp-1")
        self.assertEqual(len(history), 2)  # original + tombstone

    async def test_decision_scoped_outputs_round_trip(self) -> None:
        await self.store.set(
            "decision", "app-1:credit_assessment",
            {"credit_band": "prime", "outcome": "allow", "confidence": 0.9},
            Lineage(written_by="credit_risk_agent", decision_id="credit_assessment"),
        )

        config = {
            "decisions": [
                {
                    "id": "ltv_assessment",
                    "context_window_days": 30,
                    "depends_on": [{"decision": "credit_assessment",
                                    "required_output": "credit_band",
                                    "inherit_context": True}],
                }
            ]
        }
        builder = ContextBuilder(self.store, config)

        async def resolver(object_type_id, application_id):
            return []

        bundle = await builder.build("app-1", "ltv_assessment", resolver)
        self.assertEqual(bundle.upstream_decision_ids, ["credit_assessment"])
        self.assertIn("credit_assessment", bundle.upstream_outputs)
        self.assertEqual(
            bundle.upstream_outputs["credit_assessment"]["outcome"], "allow"
        )

    async def test_context_bundle_projects_through_ontology(self) -> None:
        await self.store.set(
            "CreditProfile", "cp-1",
            {"credit_score": 760, "credit_band": "super_prime", "derogatory_marks": 0},
            _shared_lineage(),
        )

        config = {
            "decisions": [
                {"id": "credit_assessment", "context_window_days": 90, "depends_on": []}
            ]
        }
        builder = ContextBuilder(self.store, config)

        async def resolver(object_type_id, application_id):
            return ["cp-1"] if object_type_id == "CreditProfile" else []

        bundle = await builder.build("app-1", "credit_assessment", resolver)
        self.assertIsInstance(bundle, ContextBundle)
        self.assertEqual(bundle.context_window_days, 90)

        cp = bundle.objects["CreditProfile"]["cp-1"]
        self.assertEqual(cp["_object_type"], "CreditProfile")
        self.assertEqual(cp["_decision_id"], "credit_assessment")
        self.assertEqual(cp["credit_score"], 760)

    async def test_permission_filter_blocks_unauthorized_object_types(self) -> None:
        # fraud_screening is not in CreditProfile.decisions_that_read_it.
        config = {
            "decisions": [
                {"id": "fraud_screening", "context_window_days": 30, "depends_on": []}
            ]
        }
        builder = ContextBuilder(self.store, config)

        readable = [ot.object_type_id for ot in builder.readable_object_types("fraud_screening")]
        self.assertNotIn("CreditProfile", readable)
        self.assertIn("FraudProfile", readable)

    async def test_lineage_required_on_writes(self) -> None:
        with self.assertRaises(ValueError):
            await self.store.set(
                "CreditProfile", "cp-1",
                {"credit_score": 700},
                None,  # type: ignore[arg-type]
            )

        with self.assertRaises(ValueError):
            await self.store.set(
                "CreditProfile", "cp-1",
                {"credit_score": 700},
                Lineage(written_by="", decision_id=None),
            )


if __name__ == "__main__":
    unittest.main()
