from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from .base import ContextRecord, ContextStore, Lineage, Snapshot


# ─────────────────────────────────────────────────────────────────────
# Risk-driven hot-cache TTLs.
#
# Why per-risk-level (not per-decision): low-risk decisions are cheap
# to recompute and their inputs change quickly, so short TTLs keep the
# cache fresh. High-risk decisions involve human approval — sometimes
# days — so the cache must outlast the human in the loop.
# ─────────────────────────────────────────────────────────────────────

RISK_LEVEL_TTL_SECONDS: dict[str, int] = {
    "low":    3600,            # 1h  — auto, easy to recompute
    "medium": 24 * 3600,       # 24h — semi-auto, more expensive inputs
    "high":   7 * 86400,       # 7d  — human-in-loop, must outlast review
}

DEFAULT_TTL_SECONDS = RISK_LEVEL_TTL_SECONDS["medium"]


# Pulled from domains/lending/decisions.yaml — must stay in sync.
DECISION_RISK_LEVELS: dict[str, str] = {
    "lead_scoring":          "low",
    "income_verification":   "medium",
    "credit_assessment":     "medium",
    "fraud_screening":       "high",
    "compliance_check":      "high",
    "dti_calculation":       "low",
    "ltv_assessment":        "low",
    "product_eligibility":   "medium",
    "rate_pricing":          "medium",
    "underwriting_decision": "high",
    "approval_routing":      "low",
    "closing_readiness":     "high",
}


# Per-decision cache namespace — keeps each decision's outputs isolated
# in the hot store so a leaky key in one decision can't return bytes
# from another.
DECISION_TTL_SECONDS: dict[str, int] = {
    decision: RISK_LEVEL_TTL_SECONDS[risk]
    for decision, risk in DECISION_RISK_LEVELS.items()
}


class _DurableProtocol:
    async def insert_record(self, record: ContextRecord) -> ContextRecord: ...
    async def get_latest(
        self, entity_type: str, entity_id: str, decision_id: Optional[str]
    ) -> Optional[ContextRecord]: ...
    async def get_at_time(
        self, entity_type: str, entity_id: str, decision_id: Optional[str], at: datetime
    ) -> Optional[ContextRecord]: ...
    async def history(
        self, entity_type: str, entity_id: str, decision_id: Optional[str], limit: int
    ) -> list[ContextRecord]: ...
    async def insert_snapshot(self, snapshot: Snapshot) -> Snapshot: ...
    async def tombstone(
        self, entity_type: str, entity_id: str, decision_id: Optional[str], lineage: Lineage
    ) -> int: ...


class _HotProtocol:
    async def get(
        self, entity_type: str, entity_id: str, decision_id: Optional[str]
    ) -> Optional[ContextRecord]: ...
    async def set(self, record: ContextRecord, ttl_seconds: int) -> None: ...
    async def invalidate(
        self, entity_type: str, entity_id: str, decision_id: Optional[str]
    ) -> None: ...


class LendingContextStore(ContextStore):
    """Lending-domain ContextStore.

    Composes a Redis-style hot cache with a Postgres-style durable store.
    TTLs are derived from each decision's risk_level. Provides
    decision-scoped accessors via :meth:`for_decision`.

    PRD §23.9 pii_access_always_logged: when a `pii_access_log` is
    wired, every successful read whose returned record carries PII
    fields produces an entry. Detection uses
    `core.audit.pii_log.detect_pii_fields`. Logging is best-effort — a
    failure inside the log MUST NOT break the read."""

    def __init__(
        self,
        hot: _HotProtocol,
        durable: _DurableProtocol,
        *,
        pii_access_log: Optional[Any] = None,
    ):
        self._hot = hot
        self._durable = durable
        self._pii_access_log = pii_access_log

    def attach_pii_log(self, pii_access_log: Any) -> None:
        """Late-binding hook so api/deps can install the log after the
        store is constructed (the platform builder creates the log
        alongside the audit_store, both downstream of this object)."""
        self._pii_access_log = pii_access_log

    # ── TTL policy ────────────────────────────────────────────────────

    def ttl_for(self, decision_id: Optional[str]) -> int:
        if decision_id is None:
            return DEFAULT_TTL_SECONDS
        return DECISION_TTL_SECONDS.get(decision_id, DEFAULT_TTL_SECONDS)

    @staticmethod
    def risk_level_for(decision_id: str) -> str:
        return DECISION_RISK_LEVELS.get(decision_id, "medium")

    # ── Reads ─────────────────────────────────────────────────────────

    async def get(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str] = None,
    ) -> Optional[ContextRecord]:
        cached = await self._hot.get(entity_type, entity_id, decision_id)
        if cached is not None:
            await self._log_pii_read_if_any(cached, decision_id)
            return cached
        record = await self._durable.get_latest(entity_type, entity_id, decision_id)
        if record is not None and record.superseded_at is None:
            await self._hot.set(record, self.ttl_for(decision_id))
        if record is not None:
            await self._log_pii_read_if_any(record, decision_id)
        return record

    async def _log_pii_read_if_any(
        self, record: ContextRecord, decision_id: Optional[str]
    ) -> None:
        """Best-effort PRD §23.9 pii_access_always_logged hook. Skips
        silently when no log is wired or detection finds no PII fields.
        Errors inside the log don't propagate — the audit/log path must
        never break a context read."""

        log = self._pii_access_log
        if log is None:
            return
        try:
            from core.audit.pii_log import PIIAccessEntry, detect_pii_fields
        except Exception:
            return
        try:
            value = record.value if isinstance(record.value, dict) else None
            fields = detect_pii_fields(value)
            if not fields:
                return
            application_id = None
            if isinstance(value, dict):
                application_id = value.get("application_id")
            entry = PIIAccessEntry(
                entity_type=record.entity_type,
                entity_id=record.entity_id,
                application_id=application_id,
                pii_fields=fields,
                caller=decision_id or "system",
            )
            await log.record(entry)
        except Exception:
            return

    async def history(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[ContextRecord]:
        return await self._durable.history(entity_type, entity_id, decision_id, limit)

    # ── Writes ────────────────────────────────────────────────────────

    async def set(
        self,
        entity_type: str,
        entity_id: str,
        value: dict[str, Any],
        lineage: Lineage,
    ) -> ContextRecord:
        self._validate_lineage(lineage)
        decision_id = lineage.decision_id
        record = ContextRecord(
            entity_type=entity_type,
            entity_id=entity_id,
            decision_id=decision_id,
            value=value,
            lineage=lineage,
        )
        record = await self._durable.insert_record(record)
        await self._hot.set(record, self.ttl_for(decision_id))
        return record

    async def delete(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str] = None,
        lineage: Optional[Lineage] = None,
    ) -> int:
        # Append-only history — delete = tombstone. Lineage is required
        # so the audit trail captures who deleted and why.
        tombstone_lineage = lineage or Lineage(
            decision_id=decision_id,
            written_by="system",
            notes="tombstone",
        )
        self._validate_lineage(tombstone_lineage)
        n = await self._durable.tombstone(
            entity_type, entity_id, decision_id, tombstone_lineage
        )
        await self._hot.invalidate(entity_type, entity_id, decision_id)
        return n

    # ── Snapshots ─────────────────────────────────────────────────────

    async def snapshot(
        self,
        application_id: str,
        decision_id: str,
        entity_keys: list[tuple[str, str]],
        upstream_decision_ids: Optional[list[str]] = None,
        at: Optional[datetime] = None,
    ) -> Snapshot:
        records: list[ContextRecord] = []
        merged: dict[str, Any] = {}

        for entity_type, entity_id in entity_keys:
            rec: Optional[ContextRecord]
            if at is not None:
                rec = await self._durable.get_at_time(entity_type, entity_id, None, at)
            else:
                rec = await self.get(entity_type, entity_id)
            if rec is None or rec.superseded_at is not None:
                continue
            records.append(rec)
            merged.setdefault(entity_type, {})[entity_id] = rec.value

        for upstream in upstream_decision_ids or []:
            if at is not None:
                rec = await self._durable.get_at_time(
                    "decision", f"{application_id}:{upstream}", upstream, at
                )
            else:
                rec = await self._durable.get_latest(
                    "decision", f"{application_id}:{upstream}", upstream
                )
            if rec is None or rec.superseded_at is not None:
                continue
            records.append(rec)
            merged.setdefault("decision", {})[upstream] = rec.value

        snap = Snapshot(
            application_id=application_id,
            decision_id=decision_id,
            context=merged,
            record_ids=[r.id for r in records],
            upstream_decision_ids=list(upstream_decision_ids or []),
        )
        return await self._durable.insert_snapshot(snap)

    # ── Per-decision scoped store ─────────────────────────────────────

    def for_decision(self, decision_id: str) -> "DecisionScopedStore":
        return DecisionScopedStore(self, decision_id)


class DecisionScopedStore:
    """Thin wrapper that pins decision_id on every write so a decision
    agent can't accidentally write into another decision's namespace."""

    def __init__(self, parent: LendingContextStore, decision_id: str):
        self._parent = parent
        self._decision_id = decision_id

    @property
    def decision_id(self) -> str:
        return self._decision_id

    async def get(self, entity_type: str, entity_id: str) -> Optional[ContextRecord]:
        return await self._parent.get(entity_type, entity_id, self._decision_id)

    async def get_shared(self, entity_type: str, entity_id: str) -> Optional[ContextRecord]:
        return await self._parent.get(entity_type, entity_id, None)

    async def set(
        self,
        entity_type: str,
        entity_id: str,
        value: dict[str, Any],
        agent: str,
        confidence: float = 1.0,
        upstream_decision_ids: Optional[list[str]] = None,
        source_event_id: Optional[Any] = None,
        notes: Optional[str] = None,
    ) -> ContextRecord:
        lineage = Lineage(
            decision_id=self._decision_id,
            agent=agent,
            source_event_id=source_event_id,
            upstream_decision_ids=list(upstream_decision_ids or []),
            written_by=agent,
            confidence=confidence,
            notes=notes,
        )
        return await self._parent.set(entity_type, entity_id, value, lineage)

    async def delete(self, entity_type: str, entity_id: str, agent: str) -> int:
        lineage = Lineage(
            decision_id=self._decision_id,
            agent=agent,
            written_by=agent,
            notes="tombstone",
        )
        return await self._parent.delete(entity_type, entity_id, self._decision_id, lineage)

    async def snapshot(
        self,
        application_id: str,
        entity_keys: list[tuple[str, str]],
        upstream_decision_ids: Optional[list[str]] = None,
    ) -> Snapshot:
        return await self._parent.snapshot(
            application_id=application_id,
            decision_id=self._decision_id,
            entity_keys=entity_keys,
            upstream_decision_ids=upstream_decision_ids,
        )
