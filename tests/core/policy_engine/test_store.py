"""PolicyStore tests — put/get/idempotency/active_version/scope match.

  python -m unittest tests.core.policy_engine.test_store
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
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
    PolicyRecord,
    PolicyStore,
    PolicyVersionRecord,
)


def _store() -> PolicyStore:
    backing = LendingContextStore(InMemoryHotCache(), InMemoryDurableStore())
    return PolicyStore(backing)


def _policy(
    *,
    policy_id: str = "lender_overlay::credit_assessment",
    decision_id: str = "credit_assessment",
    agency: str = "lender_overlay",
    product_scope: list[str] | None = None,
    state_scope: list[str] | None = None,
) -> PolicyRecord:
    return PolicyRecord(
        policy_id=policy_id,
        name="test policy",
        owner_team="credit_risk",
        agency=agency,
        decision_id=decision_id,
        product_scope=product_scope or [],
        state_scope=state_scope or [],
    )


def _version(
    *,
    policy_version_id: str = "lender_overlay::credit_assessment::v1",
    policy_id: str = "lender_overlay::credit_assessment",
    version_number: int = 1,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    boundary: dict | None = None,
) -> PolicyVersionRecord:
    return PolicyVersionRecord(
        policy_version_id=policy_version_id,
        policy_id=policy_id,
        version_number=version_number,
        valid_from=valid_from or datetime(2020, 1, 1),
        valid_to=valid_to,
        boundary=boundary or {"automate_if": ["credit_score >= 680"]},
        ingested_at=datetime(2026, 1, 1),
    )


class PolicyStoreBasicTests(unittest.IsolatedAsyncioTestCase):

    async def test_put_get_policy_round_trip(self):
        store = _store()
        await store.put_policy(_policy())
        got = await store.get_policy("lender_overlay::credit_assessment")
        self.assertIsNotNone(got)
        self.assertEqual(got.agency, "lender_overlay")
        self.assertEqual(got.decision_id, "credit_assessment")

    async def test_put_get_version_round_trip(self):
        store = _store()
        await store.put_policy_version(_version())
        got = await store.get_policy_version(
            "lender_overlay::credit_assessment::v1"
        )
        self.assertIsNotNone(got)
        self.assertEqual(got.version_number, 1)
        self.assertIn("automate_if", got.boundary)

    async def test_get_unknown_returns_none(self):
        store = _store()
        self.assertIsNone(await store.get_policy("nonexistent"))
        self.assertIsNone(await store.get_policy_version("nonexistent::v1"))

    async def test_list_policies_filters_by_active_only(self):
        store = _store()
        await store.put_policy(_policy())
        result = await store.list_policies()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].policy_id, "lender_overlay::credit_assessment")


class PolicyStoreIdempotencyTests(unittest.IsolatedAsyncioTestCase):

    async def test_byte_identical_put_policy_does_not_supersede(self):
        store = _store()
        backing = store._store._durable  # type: ignore[attr-defined]
        await store.put_policy(_policy())
        records_before = len(backing._records)
        await store.put_policy(_policy())  # same bytes
        self.assertEqual(len(backing._records), records_before)

    async def test_byte_identical_put_version_does_not_supersede(self):
        store = _store()
        backing = store._store._durable  # type: ignore[attr-defined]
        await store.put_policy_version(_version())
        records_before = len(backing._records)
        await store.put_policy_version(_version())  # same bytes
        self.assertEqual(len(backing._records), records_before)

    async def test_modified_put_supersedes(self):
        store = _store()
        backing = store._store._durable  # type: ignore[attr-defined]
        await store.put_policy(_policy())
        records_before = len(backing._records)
        # Change a field — different bytes triggers supersession.
        await store.put_policy(_policy(state_scope=["CA"]))
        self.assertEqual(len(backing._records), records_before + 1)

    async def test_close_version_sets_valid_to(self):
        store = _store()
        await store.put_policy_version(_version())
        cutover = datetime(2026, 6, 1)
        updated = await store.close_version(
            "lender_overlay::credit_assessment::v1", valid_to=cutover
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.valid_to, cutover)
        # Confirm by re-reading.
        again = await store.get_policy_version(
            "lender_overlay::credit_assessment::v1"
        )
        self.assertEqual(again.valid_to, cutover)

    async def test_close_version_idempotent(self):
        store = _store()
        backing = store._store._durable  # type: ignore[attr-defined]
        await store.put_policy_version(_version())
        cutover = datetime(2026, 6, 1)
        await store.close_version(
            "lender_overlay::credit_assessment::v1", valid_to=cutover
        )
        records_after_first = len(backing._records)
        # Second close with the same valid_to should be a no-op.
        await store.close_version(
            "lender_overlay::credit_assessment::v1", valid_to=cutover
        )
        self.assertEqual(len(backing._records), records_after_first)

    async def test_close_version_unknown_returns_none(self):
        store = _store()
        result = await store.close_version("ghost::v1", valid_to=datetime.utcnow())
        self.assertIsNone(result)


class PolicyStoreActiveVersionTests(unittest.IsolatedAsyncioTestCase):

    async def test_active_version_returns_none_when_no_policy(self):
        store = _store()
        result = await store.active_version(
            "credit_assessment", "lender_overlay", at=datetime.utcnow()
        )
        self.assertIsNone(result)

    async def test_active_version_finds_seeded(self):
        store = _store()
        await store.put_policy(_policy())
        await store.put_policy_version(_version())
        result = await store.active_version(
            "credit_assessment",
            "lender_overlay",
            at=datetime(2026, 5, 1),
        )
        self.assertIsNotNone(result)
        self.assertEqual(
            result.policy_version_id, "lender_overlay::credit_assessment::v1"
        )

    async def test_active_version_filters_by_at_window(self):
        store = _store()
        await store.put_policy(_policy())
        await store.put_policy_version(
            _version(
                valid_from=datetime(2025, 1, 1),
                valid_to=datetime(2025, 12, 31),
            )
        )
        # Inside window.
        inside = await store.active_version(
            "credit_assessment", "lender_overlay", at=datetime(2025, 6, 1)
        )
        self.assertIsNotNone(inside)
        # Before window.
        before = await store.active_version(
            "credit_assessment", "lender_overlay", at=datetime(2024, 6, 1)
        )
        self.assertIsNone(before)
        # After window.
        after = await store.active_version(
            "credit_assessment", "lender_overlay", at=datetime(2026, 6, 1)
        )
        self.assertIsNone(after)

    async def test_active_version_picks_higher_version_number(self):
        store = _store()
        await store.put_policy(_policy())
        await store.put_policy_version(
            _version(policy_version_id="v1", version_number=1)
        )
        await store.put_policy_version(
            _version(policy_version_id="v2", version_number=2)
        )
        result = await store.active_version(
            "credit_assessment", "lender_overlay", at=datetime(2026, 5, 1)
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.version_number, 2)

    async def test_active_version_filters_by_decision_id_and_agency(self):
        store = _store()
        # Two policies with different agencies.
        await store.put_policy(_policy(
            policy_id="lender_overlay::ca",
            agency="lender_overlay",
        ))
        await store.put_policy_version(_version(
            policy_version_id="lender_overlay::ca::v1",
            policy_id="lender_overlay::ca",
        ))
        await store.put_policy(_policy(
            policy_id="fha::ca",
            agency="fha",
        ))
        await store.put_policy_version(_version(
            policy_version_id="fha::ca::v1",
            policy_id="fha::ca",
        ))

        # Asking for fha returns the fha version, not lender_overlay's.
        fha = await store.active_version(
            "credit_assessment", "fha", at=datetime(2026, 5, 1)
        )
        self.assertIsNotNone(fha)
        self.assertEqual(fha.policy_id, "fha::ca")

        # Unknown agency returns None.
        nope = await store.active_version(
            "credit_assessment", "phantom", at=datetime(2026, 5, 1)
        )
        self.assertIsNone(nope)


class PolicyStoreScopeTests(unittest.IsolatedAsyncioTestCase):

    async def test_empty_scope_matches_all(self):
        store = _store()
        await store.put_policy(_policy())  # no product_scope, no state_scope
        await store.put_policy_version(_version())
        # Even when product/state are passed, an empty-scope policy matches.
        result = await store.active_version(
            "credit_assessment",
            "lender_overlay",
            at=datetime(2026, 5, 1),
            product="conforming",
            state="CA",
        )
        self.assertIsNotNone(result)

    async def test_product_scope_filters(self):
        store = _store()
        await store.put_policy(_policy(product_scope=["fha"]))
        await store.put_policy_version(_version())
        # Match.
        ok = await store.active_version(
            "credit_assessment",
            "lender_overlay",
            at=datetime(2026, 5, 1),
            product="fha",
        )
        self.assertIsNotNone(ok)
        # Miss — wrong product.
        miss = await store.active_version(
            "credit_assessment",
            "lender_overlay",
            at=datetime(2026, 5, 1),
            product="va",
        )
        self.assertIsNone(miss)

    async def test_state_scope_filters(self):
        store = _store()
        await store.put_policy(_policy(state_scope=["CA", "NY"]))
        await store.put_policy_version(_version())
        ca = await store.active_version(
            "credit_assessment",
            "lender_overlay",
            at=datetime(2026, 5, 1),
            state="CA",
        )
        self.assertIsNotNone(ca)
        tx = await store.active_version(
            "credit_assessment",
            "lender_overlay",
            at=datetime(2026, 5, 1),
            state="TX",
        )
        self.assertIsNone(tx)

    async def test_specific_scope_beats_default(self):
        # Two policies for same (decision, agency): one default-scope,
        # one CA-only. CA query should pick the CA-specific policy.
        store = _store()
        await store.put_policy(_policy(
            policy_id="lender_overlay::default",
        ))
        await store.put_policy_version(_version(
            policy_version_id="lender_overlay::default::v1",
            policy_id="lender_overlay::default",
        ))
        await store.put_policy(_policy(
            policy_id="lender_overlay::ca",
            state_scope=["CA"],
        ))
        await store.put_policy_version(_version(
            policy_version_id="lender_overlay::ca::v1",
            policy_id="lender_overlay::ca",
        ))
        result = await store.active_version(
            "credit_assessment",
            "lender_overlay",
            at=datetime(2026, 5, 1),
            state="CA",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.policy_id, "lender_overlay::ca")


if __name__ == "__main__":
    unittest.main()
