"""Post-decision outcome tracker — PRD STEP 12.

Captures ground-truth business outcomes after a decision has been
made and (in production) acted upon. The DAG produces
DecisionTraces; the OutcomeTracker layers in *what actually
happened* — was the loan funded, withdrawn, charged off, etc.

This closes the learning loop: AgentLearning currently captures
human overrides at decision time. With outcomes feeding in, the
reflection service can flag traces whose outcomes diverge from
prediction (e.g. an ALLOW that defaulted within 90 days) so the
agent learns from late-arriving signal too.

The tracker is append-only (one OutcomeRecord per
application_id × outcome_type). Multiple outcome types can apply
to the same application over its lifecycle (funded → defaulted →
charged_off). Latest read is by `recorded_at`.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class OutcomeType(str, Enum):
    """Closed list of post-decision business outcomes for the lending
    domain. Add to this list when a new business signal lands; never
    rename — outcomes are stamped on append-only records and renaming
    breaks historical reads.

    Time horizons (informational):
      funded                — within 60 days of approval
      withdrawn             — borrower walked at any point pre-funding
      declined_by_borrower  — explicit rejection of approval terms
      default               — 90+ days delinquent post-funding
      charged_off           — written off as uncollectable
      paid_in_full          — closed early or on schedule
      modified              — loan terms changed post-origination
    """

    FUNDED               = "funded"
    WITHDRAWN            = "withdrawn"
    DECLINED_BY_BORROWER = "declined_by_borrower"
    DEFAULT              = "default"
    CHARGED_OFF          = "charged_off"
    PAID_IN_FULL         = "paid_in_full"
    MODIFIED             = "modified"


class OutcomeRecord(BaseModel):
    """Append-only outcome row. One per application × outcome_type
    × recorded_at — late-arriving signals (e.g. a default 6 months
    after funding) become new rows, never overwrites of the original
    funded row. The tracker preserves the full history so reflection
    can correlate decision → outcome trajectories."""

    outcome_id: UUID = Field(default_factory=uuid4)
    application_id: str
    outcome_type: OutcomeType
    recorded_at: datetime = Field(default_factory=datetime.utcnow)
    occurred_at: Optional[datetime] = None  # when the event itself happened
    source: str = "manual"                  # manual / servicer / collections / etc
    reason: Optional[str] = None
    amount: Optional[float] = None          # funded amount, default balance, etc
    metadata: dict[str, Any] = Field(default_factory=dict)


class OutcomeTracker(Protocol):
    """Append-only outcome persistence."""

    async def capture(self, record: OutcomeRecord) -> UUID: ...
    async def get(self, outcome_id: UUID) -> Optional[OutcomeRecord]: ...
    async def list_for_application(
        self, application_id: str
    ) -> list[OutcomeRecord]: ...
    async def latest_for_application(
        self, application_id: str
    ) -> Optional[OutcomeRecord]: ...
    async def list_by_type(
        self, outcome_type: OutcomeType
    ) -> list[OutcomeRecord]: ...


class InMemoryOutcomeTracker:
    """Reference implementation. Postgres swap mirrors the contract
    on top of an outcomes table; the schema is straightforward
    (outcome_id PK + application_id idx + occurred_at + JSONB metadata)
    and follows the same append-only pattern as audit_records."""

    def __init__(self) -> None:
        self._records: dict[UUID, OutcomeRecord] = {}

    async def capture(self, record: OutcomeRecord) -> UUID:
        if record.outcome_id in self._records:
            raise ValueError(
                f"outcome_id {record.outcome_id} already captured; "
                f"outcomes are append-only"
            )
        self._records[record.outcome_id] = record
        return record.outcome_id

    async def get(self, outcome_id: UUID) -> Optional[OutcomeRecord]:
        return self._records.get(outcome_id)

    async def list_for_application(
        self, application_id: str
    ) -> list[OutcomeRecord]:
        rows = [
            r for r in self._records.values()
            if r.application_id == application_id
        ]
        rows.sort(key=lambda r: r.recorded_at)
        return rows

    async def latest_for_application(
        self, application_id: str
    ) -> Optional[OutcomeRecord]:
        rows = await self.list_for_application(application_id)
        return rows[-1] if rows else None

    async def list_by_type(
        self, outcome_type: OutcomeType
    ) -> list[OutcomeRecord]:
        return [
            r for r in self._records.values()
            if r.outcome_type == outcome_type
        ]

    def __len__(self) -> int:
        return len(self._records)


# ─────────────────────────────────────────────────────────────────────
# Decision↔outcome correlation — the read shape that powers learning.
# ─────────────────────────────────────────────────────────────────────


class DecisionOutcomeCorrelation(BaseModel):
    """Joins a final-stage DecisionTrace (underwriting / closing) to
    the eventual business outcomes. Reflection consumes this to flag
    miscalibrated agents — an ALLOW that ended up DEFAULT, a BLOCK
    that the human overrode and DID fund successfully."""

    application_id: str
    decision_id: str                 # e.g. "underwriting_decision"
    decision_outcome: str            # allow / recommend / escalate / block
    confidence: Optional[float] = None
    outcomes: list[OutcomeRecord] = Field(default_factory=list)
    final_outcome_type: Optional[OutcomeType] = None  # latest outcome
    days_to_first_outcome: Optional[int] = None


def correlate(
    application_id: str,
    *,
    decision_id: str,
    decision_outcome: str,
    decision_confidence: Optional[float],
    decision_at: datetime,
    outcomes: list[OutcomeRecord],
) -> DecisionOutcomeCorrelation:
    """Pure function — caller pulls the trace + outcomes and we
    assemble the correlation. Kept stateless so tests + reports + UI
    all share one assembly path."""

    outcomes_sorted = sorted(outcomes, key=lambda r: r.recorded_at)
    final = outcomes_sorted[-1].outcome_type if outcomes_sorted else None
    days = None
    if outcomes_sorted:
        first_at = outcomes_sorted[0].occurred_at or outcomes_sorted[0].recorded_at
        delta = first_at - decision_at
        days = max(0, delta.days)
    return DecisionOutcomeCorrelation(
        application_id=application_id,
        decision_id=decision_id,
        decision_outcome=decision_outcome,
        confidence=decision_confidence,
        outcomes=outcomes_sorted,
        final_outcome_type=final,
        days_to_first_outcome=days,
    )


__all__ = [
    "DecisionOutcomeCorrelation",
    "InMemoryOutcomeTracker",
    "OutcomeRecord",
    "OutcomeTracker",
    "OutcomeType",
    "correlate",
]
