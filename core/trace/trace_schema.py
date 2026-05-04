from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from core.normalizer.models import DecisionMode, DecisionOutcome, RiskLevel


# ─────────────────────────────────────────────────────────────────────
# WorkJournalEntry — structured reasoning, not a string blob.
#
# Why structured: a free-text reasoning field cannot be audited, cannot
# be checked by a critic agent, and cannot be replayed. Structured
# fields force the agent to expose hypothesis, signals, contradictions
# and confidence basis — which is exactly what the critic and the
# governance layer need to verify.
# ─────────────────────────────────────────────────────────────────────


class SignalDirection(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"


class Signal(BaseModel):
    name: str
    value: Any
    weight: Optional[float] = None
    direction: SignalDirection = SignalDirection.NEUTRAL
    source: Optional[str] = None
    notes: Optional[str] = None


class Contradiction(BaseModel):
    signal_a: str
    signal_b: str
    description: str
    resolved: bool = False
    resolution: Optional[str] = None


class WorkJournalEntry(BaseModel):
    """Structured replacement for a free-text 'reasoning' field.

    Every decision agent must produce one of these. Empty strings or
    empty signal lists will fail critic review."""

    hypothesis_tested: str
    signals_evaluated: list[Signal] = Field(default_factory=list)
    contradictions_found: list[Contradiction] = Field(default_factory=list)
    conclusion: str
    confidence_basis: str
    human_readable_summary: str


# ─────────────────────────────────────────────────────────────────────
# Reviews
# ─────────────────────────────────────────────────────────────────────


class CriticVerdict(str, Enum):
    APPROVED = "approved"
    FLAGGED = "flagged"
    ESCALATED = "escalated"


class CriticReview(BaseModel):
    critic_id: str
    reviewed_at: datetime = Field(default_factory=datetime.utcnow)
    verdict: CriticVerdict
    findings: list[str] = Field(default_factory=list)
    confidence: float = 1.0


class HumanReview(BaseModel):
    reviewer_id: str
    reviewer_role: str
    reviewed_at: datetime = Field(default_factory=datetime.utcnow)
    original_ai_decision: DecisionOutcome
    final_outcome: DecisionOutcome
    overridden: bool = False
    override_reason: Optional[str] = None
    override_reason_code: Optional[str] = None
    notes: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────
# Claim provenance — the frozen list of evidence that drove a decision
# ─────────────────────────────────────────────────────────────────────


class ClaimProvenance(BaseModel):
    """Frozen reference to a Claim that drove this decision's outcome.

    Captures the claim's value AS SEEN at decision time. Decoupled
    from the live KnowledgeStore so a re-extraction or re-verification
    of the source claim can't retroactively change what the trace says.
    Regulators reconstruct a decision by reading these alongside the
    work journal — this is the audit chain from outcome back to
    source document and verifier."""

    claim_id: str
    field_name: str
    field_value: Any = None
    document_id: str
    source_page: Optional[int] = None
    status: str = "verified"
    verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    extraction_confidence: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────
# DecisionTrace — full execution record, satisfies the
# "no_execution_without_trace" hard rule.
# ─────────────────────────────────────────────────────────────────────


class DecisionTrace(BaseModel):
    trace_id: UUID = Field(default_factory=uuid4)

    # Identity
    decision_id: str
    application_id: str
    agent_id: str
    persona: str
    mode: DecisionMode
    risk_level: RiskLevel

    # Inputs
    inputs_snapshot_id: UUID
    upstream_decision_ids: list[str] = Field(default_factory=list)
    context_window_days: Optional[int] = None

    # Reasoning (structured — see WorkJournalEntry)
    reasoning: WorkJournalEntry

    # Outputs
    outcome: DecisionOutcome
    confidence: float
    matched_clause: Optional[str] = None
    output_payload: dict[str, Any] = Field(default_factory=dict)

    # Policy + reviews
    policy_decision_outcome: Optional[DecisionOutcome] = None
    policy_matched_clause: Optional[str] = None
    policy_reasons: list[str] = Field(default_factory=list)
    contamination: bool = False

    # Type-2 policy versioning. policy_version_id pinpoints the exact
    # PolicyVersion that produced the outcome — required for replay
    # correctness and regulator audit. policy_chain lists every agency's
    # version consulted (in overlay-first order); for v1 with only the
    # lender_overlay seeded it carries one entry.
    policy_version_id: Optional[str] = None
    policy_chain: list[str] = Field(default_factory=list)

    # Frozen list of Claims (evidence) consumed at decision time.
    # See ClaimProvenance — regulators trace outcome → claim → document
    # → verifier through this field. Empty when the decision didn't
    # consume any verified claims (e.g. lead_scoring runs before any
    # docs are uploaded).
    claim_provenance: list[ClaimProvenance] = Field(default_factory=list)

    critic_review: Optional[CriticReview] = None
    human_review: Optional[HumanReview] = None

    # Timing
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    # Versioning
    domain: str = "lending"
    spec_version: Optional[str] = None
