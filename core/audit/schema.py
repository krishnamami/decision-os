from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from core.normalizer.models import DecisionMode, DecisionOutcome


# ─────────────────────────────────────────────────────────────────────
# AuditRecord — append-only artefact written for every decision before
# any external writeback executes (PRD §23, hard rule
# audit_record_required_before_writeback).
#
# Why a separate type from DecisionTrace: a trace captures the agent's
# reasoning; an audit record captures the regulator-facing
# perspective — who saw what, which protected attributes were touched,
# which regulations apply, whether the decision is biased or
# anomalous. The two are stored side-by-side and never overwritten.
# ─────────────────────────────────────────────────────────────────────


class CheckStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class ConsentStatus(str, Enum):
    OBTAINED = "obtained"
    PENDING = "pending"
    MISSING = "missing"
    WITHDRAWN = "withdrawn"


class DataClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class EncryptionStatus(str, Enum):
    AT_REST = "encrypted_at_rest"
    IN_TRANSIT = "in_transit"
    BOTH = "both"


# ─────────────────────────────────────────────────────────────────────
# Sub-models for jsonb columns
# ─────────────────────────────────────────────────────────────────────


class PolicyApplied(BaseModel):
    """One row in audit_records.policy_applied[]. Mirrors
    DecisionTrace.policies_evaluated but frozen at audit time so the
    audit record is self-contained for regulator export."""

    policy_id: str
    clause: Optional[str] = None
    result: str
    reason: Optional[str] = None


class AccessRecord(BaseModel):
    """One row in audit_records.accessed_by[]. Recorded in the access
    log every time a PII field is read for this decision (PRD §23.9
    pii_access_always_logged)."""

    user_id: str
    role: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    action: str
    ip_hash: Optional[str] = None


class FairnessFlag(BaseModel):
    """One row in audit_records.fairness_flags[]. Produced by the
    fairness checker when a segment deviates from the baseline rate
    or when a protected attribute appears in the agent's reasoning
    surface."""

    attribute: str
    flag_type: str
    description: str
    severity: str = "warn"


class CheckResult(BaseModel):
    """Per-check return type. Engine assembles four of these into the
    AuditRecord and aggregates the worst status to the record level."""

    name: str
    status: CheckStatus
    findings: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────
# AuditRecord — full schema per PRD §23.3
# ─────────────────────────────────────────────────────────────────────


class AuditRecord(BaseModel):
    """Append-only audit artefact. One per decision. Never deleted.

    Corrections are new rows with supersedes_audit_id pointing at the
    prior record. The store enforces the no-delete invariant at the
    Python layer; production Postgres revokes DELETE on the role."""

    # ── Identity ─────────────────────────────────────────────────────
    audit_id: UUID = Field(default_factory=uuid4)
    decision_id: UUID
    application_id: str
    decision_type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    supersedes_audit_id: Optional[UUID] = None

    # ── Decision block ───────────────────────────────────────────────
    event_input: dict[str, Any] = Field(default_factory=dict)
    context_used: dict[str, Any] = Field(default_factory=dict)
    ontology_mapping: dict[str, Any] = Field(default_factory=dict)
    policy_applied: list[PolicyApplied] = Field(default_factory=list)
    decision_output: DecisionOutcome
    confidence: float
    owner: str
    mode: DecisionMode
    execution_result: dict[str, Any] = Field(default_factory=dict)
    outcome: Optional[str] = None  # final business outcome (funded, withdrawn, ...)

    # ── Compliance block ─────────────────────────────────────────────
    regulation_tags: list[str] = Field(default_factory=list)
    consent_status: ConsentStatus = ConsentStatus.OBTAINED
    data_sources_used: list[str] = Field(default_factory=list)
    disclosure_sent: bool = False
    disclosure_timestamp: Optional[datetime] = None
    retention_policy: Optional[str] = None
    compliance_status: CheckStatus = CheckStatus.PASS

    # ── Security block ───────────────────────────────────────────────
    accessed_by: list[AccessRecord] = Field(default_factory=list)
    permissions_used: list[str] = Field(default_factory=list)
    data_classification: DataClassification = DataClassification.CONFIDENTIAL
    pii_fields_accessed: list[str] = Field(default_factory=list)
    encryption_status: EncryptionStatus = EncryptionStatus.BOTH
    access_anomaly: bool = False
    access_anomaly_reason: Optional[str] = None
    security_status: CheckStatus = CheckStatus.PASS

    # ── Ethics block ─────────────────────────────────────────────────
    applicant_segment: Optional[str] = None
    protected_attrs_used: list[str] = Field(default_factory=list)
    protected_attrs_excluded: list[str] = Field(default_factory=list)
    fairness_flags: list[FairnessFlag] = Field(default_factory=list)
    bias_score: Optional[float] = None
    disparate_impact_flag: bool = False
    human_reviewed: bool = False
    ethics_status: CheckStatus = CheckStatus.PASS
    fairness_status: CheckStatus = CheckStatus.PASS

    # ── Aggregate status ─────────────────────────────────────────────
    overall_status: CheckStatus = CheckStatus.PASS
