from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from core.context_store.base import Lineage
from core.context_store.lending import LendingContextStore


# ─────────────────────────────────────────────────────────────────────
# PolicyStore — read+write facade over LendingContextStore for the two
# policy-related ObjectTypes (Policy, PolicyVersion).
#
# Why a facade and not new storage:
#   - Policy / PolicyVersion get the same Type-2 supersession + lineage
#     + point-in-time semantics every other entity gets.
#   - Postgres swap is one transaction, not a second backend.
#   - decisions_that_read_it on Policy / PolicyVersion already filters
#     reads at the projection layer.
#
# Scope: SHARED (decision_id=None) on every write. Policies are
# cross-application. The PolicyEvaluator will read them keyed by
# (decision_id, agency, at) — see active_version() below.
#
# `at` semantics: PolicyVersion has TWO time axes:
#   - business effectivity: valid_from / valid_to (when the rule was in
#     force in the world). active_version() filters on this axis.
#   - technical version: version + ContextStore supersession (when our
#     system stored the record). Used to update an old version's
#     valid_to when a new version arrives — we mutate the old record's
#     `valid_to` field via supersession so the chain stays auditable.
#
# In-memory walk: active_version walks durable._records in v1 because
# the store doesn't expose a "list by entity_type + predicate" API yet.
# Same pattern as api.deps._default_resolver. Postgres swap = one
# `SELECT ... WHERE entity_type = 'policy_version' AND superseded_at IS
# NULL`. Marked TODO below.
# ─────────────────────────────────────────────────────────────────────


POLICY_ENTITY_TYPE = "Policy"
POLICY_VERSION_ENTITY_TYPE = "PolicyVersion"


class PolicyRecord(BaseModel):
    """Typed view over a stored Policy value blob."""

    policy_id: str
    name: str
    description: str = ""
    owner_team: str
    agency: str
    decision_id: Optional[str] = None
    product_scope: list[str] = Field(default_factory=list)
    state_scope: list[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None

    def matches_scope(
        self, *, product: Optional[str] = None, state: Optional[str] = None
    ) -> bool:
        """Empty list = matches all. Non-empty list = membership required."""
        if self.product_scope and product is not None:
            if product not in self.product_scope:
                return False
        if self.state_scope and state is not None:
            if state not in self.state_scope:
                return False
        return True

    def scope_specificity(self) -> int:
        """Higher = more specific. Used to break ties when multiple policies
        match a given (decision_id, agency)."""
        return int(bool(self.product_scope)) + int(bool(self.state_scope))


class PolicyVersionRecord(BaseModel):
    """Typed view over a stored PolicyVersion value blob."""

    policy_version_id: str
    policy_id: str
    version_number: int = 1
    valid_from: datetime
    valid_to: Optional[datetime] = None
    source_url: Optional[str] = None
    source_revision: Optional[str] = None
    boundary: dict[str, Any] = Field(default_factory=dict)
    contamination_guard: Optional[dict[str, Any]] = None
    hard_rules_subscribed: list[str] = Field(default_factory=list)
    ingested_at: Optional[datetime] = None
    ingested_by: str = "system"

    def is_effective_at(self, at: datetime) -> bool:
        """`at` falls inside the [valid_from, valid_to) effectivity window."""
        if at < self.valid_from:
            return False
        if self.valid_to is not None and at >= self.valid_to:
            return False
        return True


class PolicyStore:
    """Read+write facade over LendingContextStore for Policy / PolicyVersion.

    Public surface:
      put_policy(policy, *, written_by)              -> PolicyRecord
      put_policy_version(version, *, written_by)     -> PolicyVersionRecord
      get_policy(policy_id)                          -> PolicyRecord | None
      get_policy_version(policy_version_id)          -> PolicyVersionRecord | None
      active_version(decision_id, agency, *, at,
                     product=None, state=None)       -> PolicyVersionRecord | None
      list_policies()                                -> list[PolicyRecord]
      list_versions(policy_id=None)                  -> list[PolicyVersionRecord]
    """

    def __init__(self, store: LendingContextStore):
        self._store = store

    # ── Writes ───────────────────────────────────────────────────────

    async def put_policy(
        self, policy: PolicyRecord, *, written_by: str = "system"
    ) -> PolicyRecord:
        """Idempotent: if an active record with identical bytes already
        exists, returns the existing record without writing."""
        existing = await self._store.get(POLICY_ENTITY_TYPE, policy.policy_id, None)
        new_value = policy.model_dump(mode="json")
        if existing is not None and isinstance(existing.value, dict):
            if existing.value == new_value:
                return PolicyRecord.model_validate(existing.value)
        lineage = Lineage(
            decision_id=None,
            agent=written_by,
            written_by=written_by,
            confidence=1.0,
            notes="policy upsert",
        )
        await self._store.set(
            POLICY_ENTITY_TYPE, policy.policy_id, new_value, lineage
        )
        return policy

    async def put_policy_version(
        self,
        version: PolicyVersionRecord,
        *,
        written_by: str = "system",
    ) -> PolicyVersionRecord:
        """Idempotent: if an active record with identical bytes already
        exists, returns the existing record without writing."""
        existing = await self._store.get(
            POLICY_VERSION_ENTITY_TYPE, version.policy_version_id, None
        )
        new_value = version.model_dump(mode="json")
        if existing is not None and isinstance(existing.value, dict):
            if existing.value == new_value:
                return PolicyVersionRecord.model_validate(existing.value)
        lineage = Lineage(
            decision_id=None,
            agent=written_by,
            written_by=written_by,
            confidence=1.0,
            notes="policy_version upsert",
        )
        await self._store.set(
            POLICY_VERSION_ENTITY_TYPE,
            version.policy_version_id,
            new_value,
            lineage,
        )
        return version

    async def close_version(
        self,
        policy_version_id: str,
        *,
        valid_to: datetime,
        written_by: str = "system",
    ) -> Optional[PolicyVersionRecord]:
        """Set valid_to on an existing PolicyVersion. Used when a newer
        bulletin supersedes an older one mid-window. No-op if the version
        already has the same valid_to or doesn't exist."""
        existing = await self.get_policy_version(policy_version_id)
        if existing is None:
            return None
        if existing.valid_to == valid_to:
            return existing
        updated = existing.model_copy(update={"valid_to": valid_to})
        return await self.put_policy_version(updated, written_by=written_by)

    # ── Reads ────────────────────────────────────────────────────────

    async def get_policy(self, policy_id: str) -> Optional[PolicyRecord]:
        rec = await self._store.get(POLICY_ENTITY_TYPE, policy_id, None)
        if rec is None or not isinstance(rec.value, dict):
            return None
        return PolicyRecord.model_validate(rec.value)

    async def get_policy_version(
        self, policy_version_id: str
    ) -> Optional[PolicyVersionRecord]:
        rec = await self._store.get(
            POLICY_VERSION_ENTITY_TYPE, policy_version_id, None
        )
        if rec is None or not isinstance(rec.value, dict):
            return None
        return PolicyVersionRecord.model_validate(rec.value)

    async def list_policies(self) -> list[PolicyRecord]:
        return [
            PolicyRecord.model_validate(value)
            for value in self._iter_active_values(POLICY_ENTITY_TYPE)
        ]

    async def list_versions(
        self, policy_id: Optional[str] = None
    ) -> list[PolicyVersionRecord]:
        out: list[PolicyVersionRecord] = []
        for value in self._iter_active_values(POLICY_VERSION_ENTITY_TYPE):
            try:
                pv = PolicyVersionRecord.model_validate(value)
            except Exception:
                continue
            if policy_id is None or pv.policy_id == policy_id:
                out.append(pv)
        return out

    async def active_version(
        self,
        decision_id: str,
        agency: str,
        *,
        at: datetime,
        product: Optional[str] = None,
        state: Optional[str] = None,
    ) -> Optional[PolicyVersionRecord]:
        """Find the PolicyVersion effective at `at` for (decision_id, agency).

        Algorithm:
          1. Match Policy candidates: decision_id == decision_id AND
             agency == agency AND scope matches `product` / `state`.
          2. For each matching Policy, find the highest-version
             PolicyVersion whose [valid_from, valid_to) covers `at`.
          3. If multiple Policy candidates match, pick the most-specific
             scope (state_scope+product_scope set) over a default-scope
             policy. Tie-broken by version_number, then policy_id.
        """
        policy_candidates: list[PolicyRecord] = [
            p for p in await self.list_policies()
            if p.decision_id == decision_id
            and p.agency == agency
            and p.matches_scope(product=product, state=state)
        ]
        if not policy_candidates:
            return None

        # Most-specific scope first, then later ties broken by version_number.
        policy_candidates.sort(
            key=lambda p: (-p.scope_specificity(), p.policy_id)
        )

        for policy in policy_candidates:
            versions = [
                v for v in await self.list_versions(policy_id=policy.policy_id)
                if v.is_effective_at(at)
            ]
            if not versions:
                continue
            versions.sort(key=lambda v: v.version_number, reverse=True)
            return versions[0]
        return None

    # ── Internal: walk the durable store's active rows for an entity_type.
    # Same pattern as api.deps._default_resolver.
    # TODO postgres: replace with `SELECT value FROM context_records
    # WHERE entity_type = $1 AND decision_id IS NULL AND superseded_at
    # IS NULL AND tombstoned_at IS NULL`.
    # ─────────────────────────────────────────────────────────────────

    def _iter_active_values(self, entity_type: str) -> list[dict[str, Any]]:
        durable = self._store._durable  # type: ignore[attr-defined]
        records = getattr(durable, "_records", None)
        if not isinstance(records, list):
            return []
        latest_by_id: dict[str, Any] = {}
        for rec in records:
            if rec.entity_type != entity_type:
                continue
            if rec.decision_id is not None:
                continue
            if rec.superseded_at is not None:
                continue
            current = latest_by_id.get(rec.entity_id)
            if current is None or rec.version > current.version:
                latest_by_id[rec.entity_id] = rec
        return [
            r.value for r in latest_by_id.values()
            if isinstance(r.value, dict)
        ]


__all__ = [
    "POLICY_ENTITY_TYPE",
    "POLICY_VERSION_ENTITY_TYPE",
    "PolicyRecord",
    "PolicyStore",
    "PolicyVersionRecord",
]
