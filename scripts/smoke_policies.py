"""Policy seeding smoke test — STREAM C (Session 9).

Boots a Platform, runs seed_policies_from_yaml against the live spec,
asserts the durable store now carries one Policy + one PolicyVersion
per decision under agency=lender_overlay, then exercises:

  1. Idempotency — re-running the seeder produces no new records.
  2. active_version() lookup — for every decision_id, agency=
     lender_overlay, at=now → returns the v1 PolicyVersion.
  3. Point-in-time correctness — at < valid_from returns None;
     at == valid_from returns v1; far-future at returns v1 (valid_to
     is null).
  4. Supersession via close_version — setting valid_to on v1 then
     putting a v2 with valid_from=v1.valid_to. active_version at the
     boundary returns v2; at an earlier date returns v1; record count
     reflects supersession (v1 record is superseded, not deleted).

Run:
  python -X utf8 scripts/smoke_policies.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.deps import build_default_platform  # noqa: E402
from core.policy_engine import (  # noqa: E402
    POLICY_ENTITY_TYPE,
    POLICY_VERSION_ENTITY_TYPE,
    PolicyVersionRecord,
    SEED_AGENCY,
    SEED_VALID_FROM,
    policy_id_for,
    policy_version_id_for,
    seed_policies_from_yaml,
)


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


async def main() -> int:
    platform = build_default_platform()
    spec = platform.spec
    policy_store = platform.policy_store
    durable = platform.store._durable  # type: ignore[attr-defined]

    decision_ids = [d["id"] for d in spec.decisions]
    expected_count = len(decision_ids)
    assert expected_count == 12, f"expected 12 decisions, got {expected_count}"

    print("Phase 1 — first seed pass.")
    policies, versions = await seed_policies_from_yaml(spec, policy_store)
    assert len(policies) == expected_count, policies
    assert len(versions) == expected_count, versions
    assert _count_active(durable, POLICY_ENTITY_TYPE) == expected_count
    assert _count_active(durable, POLICY_VERSION_ENTITY_TYPE) == expected_count
    after_pass1_total_policies = _count_total(durable, POLICY_ENTITY_TYPE)
    after_pass1_total_versions = _count_total(durable, POLICY_VERSION_ENTITY_TYPE)
    print(f"  Policies active: {expected_count}; PolicyVersions active: {expected_count}")

    print("Phase 2 — idempotency: second seed must be a no-op.")
    policies2, versions2 = await seed_policies_from_yaml(spec, policy_store)
    assert policies2 == policies
    assert versions2 == versions
    assert _count_total(durable, POLICY_ENTITY_TYPE) == after_pass1_total_policies, \
        "second seed pass churned the Policy supersession chain"
    assert _count_total(durable, POLICY_VERSION_ENTITY_TYPE) == after_pass1_total_versions, \
        "second seed pass churned the PolicyVersion supersession chain"
    print("  Re-run wrote 0 new records.")

    print("Phase 3 — active_version lookups for every decision at now().")
    now = datetime.utcnow()
    for decision_id in decision_ids:
        v = await policy_store.active_version(
            decision_id, SEED_AGENCY, at=now
        )
        assert v is not None, f"no active version for {decision_id} at now()"
        assert v.policy_version_id == policy_version_id_for(decision_id), v
        assert v.policy_id == policy_id_for(decision_id)
        assert v.version_number == 1
        assert v.valid_from == SEED_VALID_FROM
        assert v.valid_to is None
        assert isinstance(v.boundary, dict) and v.boundary, \
            f"empty boundary for {decision_id}"
    print(f"  All {expected_count} decisions resolve to v1 at now().")

    print("Phase 4 — point-in-time edges.")
    decision_id = decision_ids[0]
    before_epoch = SEED_VALID_FROM - timedelta(days=1)
    v_before = await policy_store.active_version(
        decision_id, SEED_AGENCY, at=before_epoch
    )
    assert v_before is None, "expected None for at < valid_from"
    v_at = await policy_store.active_version(
        decision_id, SEED_AGENCY, at=SEED_VALID_FROM
    )
    assert v_at is not None and v_at.version_number == 1
    far_future = datetime(2099, 1, 1)
    v_far = await policy_store.active_version(
        decision_id, SEED_AGENCY, at=far_future
    )
    assert v_far is not None and v_far.version_number == 1
    print("  before/at/after edges all correct.")

    print("Phase 5 — supersession: close v1 + add v2 mid-range.")
    cutover = datetime(2026, 1, 1)
    decision_id = "credit_assessment"
    pv1_id = policy_version_id_for(decision_id)
    closed_v1 = await policy_store.close_version(pv1_id, valid_to=cutover)
    assert closed_v1 is not None and closed_v1.valid_to == cutover
    # v1 record should now be superseded (the put_policy_version path supersedes
    # the prior bytes); active count stays at 12 because we wrote a new active
    # record reflecting the updated valid_to.
    assert _count_active(durable, POLICY_VERSION_ENTITY_TYPE) == expected_count
    assert _count_total(durable, POLICY_VERSION_ENTITY_TYPE) == \
        after_pass1_total_versions + 1, \
        "expected one new (superseding) PolicyVersion record after close_version"

    v2_id = policy_version_id_for(decision_id, version_number=2)
    v2 = PolicyVersionRecord(
        policy_version_id=v2_id,
        policy_id=policy_id_for(decision_id),
        version_number=2,
        valid_from=cutover,
        valid_to=None,
        source_revision="smoke v2",
        boundary={"automate_if": ["credit_score >= 720"]},
        ingested_at=datetime.utcnow(),
        ingested_by="scripts.smoke_policies",
    )
    await policy_store.put_policy_version(v2, written_by="scripts.smoke_policies")
    assert _count_active(durable, POLICY_VERSION_ENTITY_TYPE) == expected_count + 1
    print("  v1 valid_to updated; v2 inserted as a separate active row.")

    pre_cutover = cutover - timedelta(days=1)
    v_pre = await policy_store.active_version(
        decision_id, SEED_AGENCY, at=pre_cutover
    )
    assert v_pre is not None and v_pre.version_number == 1, \
        f"pre-cutover lookup returned {v_pre}"

    post_cutover = cutover + timedelta(days=1)
    v_post = await policy_store.active_version(
        decision_id, SEED_AGENCY, at=post_cutover
    )
    assert v_post is not None and v_post.version_number == 2, \
        f"post-cutover lookup returned {v_post}"
    print("  pre-cutover→v1, post-cutover→v2.")

    print("\nALL PHASES PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
