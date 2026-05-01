from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Lineage(BaseModel):
    """Provenance attached to every context write.

    Hard rule no_context_without_lineage — ContextStore.set() refuses
    writes where lineage is missing or written_by is empty."""

    decision_id: Optional[str] = None
    agent: Optional[str] = None
    source_event_id: Optional[UUID] = None
    upstream_decision_ids: list[str] = Field(default_factory=list)
    upstream_record_ids: list[UUID] = Field(default_factory=list)
    written_by: str = "system"
    written_at: datetime = Field(default_factory=datetime.utcnow)
    confidence: float = 1.0
    contamination_flag: bool = False
    notes: Optional[str] = None


class ContextRecord(BaseModel):
    """One versioned write of an entity's state, scoped to a decision (or
    None for shared data). Append-only — supersession flips the previous
    row, never deletes it."""

    id: UUID = Field(default_factory=uuid4)
    entity_type: str
    entity_id: str
    decision_id: Optional[str] = None
    version: int = 1
    value: dict[str, Any]
    lineage: Lineage
    superseded_at: Optional[datetime] = None
    superseded_by: Optional[UUID] = None


class Snapshot(BaseModel):
    """Frozen merged context handed to a decision agent. Captures the
    exact records the agent saw so trace can replay the inputs."""

    id: UUID = Field(default_factory=uuid4)
    application_id: str
    decision_id: str
    snapshot_at: datetime = Field(default_factory=datetime.utcnow)
    context: dict[str, Any]
    record_ids: list[UUID]
    upstream_decision_ids: list[str] = Field(default_factory=list)


class ContextStore(ABC):
    """Two-tier context store.

    - Hot cache (Redis): TTL-bounded, key = entity+decision scope.
    - Durable history (Postgres): append-only versioned records with
      full lineage; never destructively deletes — delete() marks rows
      tombstoned and evicts from the hot cache.

    All writes require a Lineage. Hard rules:
      - no_context_without_lineage
      - no_execution_without_trace (history must remain auditable)
    """

    @abstractmethod
    async def get(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str] = None,
    ) -> Optional[ContextRecord]: ...

    @abstractmethod
    async def set(
        self,
        entity_type: str,
        entity_id: str,
        value: dict[str, Any],
        lineage: Lineage,
    ) -> ContextRecord: ...

    @abstractmethod
    async def snapshot(
        self,
        application_id: str,
        decision_id: str,
        entity_keys: list[tuple[str, str]],
        upstream_decision_ids: Optional[list[str]] = None,
        at: Optional[datetime] = None,
    ) -> Snapshot: ...

    @abstractmethod
    async def delete(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str] = None,
        lineage: Optional[Lineage] = None,
    ) -> int:
        """Tombstone the active record(s) for this key. Append-only —
        nothing is physically removed from history. Returns the number
        of versions tombstoned."""
        ...

    @abstractmethod
    async def history(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[ContextRecord]: ...

    @abstractmethod
    def ttl_for(self, decision_id: Optional[str]) -> int:
        """Hot-cache TTL in seconds. 0 means no expiry."""
        ...

    @staticmethod
    def _validate_lineage(lineage: Optional[Lineage]) -> None:
        if lineage is None:
            raise ValueError("lineage is required (no_context_without_lineage)")
        if not lineage.written_by:
            raise ValueError("lineage.written_by is required (no_context_without_lineage)")
        if not 0.0 <= lineage.confidence <= 1.0:
            raise ValueError("lineage.confidence must be in [0, 1]")
