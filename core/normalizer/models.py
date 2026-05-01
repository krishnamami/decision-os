from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError


# ────────────────────────────────────────────────────────────────────────────
# Enums — mirror the vocabulary used in domains/lending/decisions.yaml
# ────────────────────────────────────────────────────────────────────────────


class EntityType(str, Enum):
    CUSTOMER = "customer"
    APPLICATION = "application"
    LEAD = "lead"
    PROPERTY = "property"
    CREDIT_REPORT = "credit_report"
    INCOME_RECORD = "income_record"
    DOCUMENT = "document"
    DECISION = "decision"


class DecisionId(str, Enum):
    LEAD_SCORING = "lead_scoring"
    INCOME_VERIFICATION = "income_verification"
    CREDIT_ASSESSMENT = "credit_assessment"
    FRAUD_SCREENING = "fraud_screening"
    COMPLIANCE_CHECK = "compliance_check"
    DTI_CALCULATION = "dti_calculation"
    LTV_ASSESSMENT = "ltv_assessment"
    PRODUCT_ELIGIBILITY = "product_eligibility"
    RATE_PRICING = "rate_pricing"
    UNDERWRITING_DECISION = "underwriting_decision"
    APPROVAL_ROUTING = "approval_routing"
    CLOSING_READINESS = "closing_readiness"


class DecisionMode(str, Enum):
    SHADOW = "shadow"
    RECOMMEND = "recommend"
    HUMAN_APPROVAL = "human_approval"
    AUTO_EXECUTE = "auto_execute"


class DecisionOutcome(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    RECOMMEND = "recommend"
    ESCALATE = "escalate"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EventType(str, Enum):
    LEAD_RECEIVED = "lead_received"
    APPLICATION_SUBMITTED = "application_submitted"
    KYC_COMPLETED = "kyc_completed"
    INCOME_DECLARED = "income_declared"
    PAYROLL_RECEIVED = "payroll_received"
    TAX_RETURN_UPLOADED = "tax_return_uploaded"
    BANK_STATEMENT_UPLOADED = "bank_statement_uploaded"
    CREDIT_PULLED = "credit_pulled"
    FRAUD_SIGNAL = "fraud_signal"
    DOCUMENT_UPLOADED = "document_uploaded"
    PROPERTY_APPRAISED = "property_appraised"
    DECISION_EMITTED = "decision_emitted"
    HUMAN_OVERRIDE = "human_override"


# ────────────────────────────────────────────────────────────────────────────
# Entity models — normalized projections of state, used by ContextStore
# ────────────────────────────────────────────────────────────────────────────


class BaseEntity(BaseModel):
    entity_type: EntityType
    entity_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Customer(BaseEntity):
    entity_type: EntityType = EntityType.CUSTOMER
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    kyc_status: Optional[str] = None


class Application(BaseEntity):
    entity_type: EntityType = EntityType.APPLICATION
    customer_id: str
    loan_purpose: Optional[str] = None
    requested_amount: Optional[float] = None
    property_state: Optional[str] = None
    status: Optional[str] = None


class Lead(BaseEntity):
    entity_type: EntityType = EntityType.LEAD
    customer_id: Optional[str] = None
    source: Optional[str] = None
    channel: Optional[str] = None
    intent_score: Optional[float] = None
    utm_params: dict[str, Any] = Field(default_factory=dict)


class Property(BaseEntity):
    entity_type: EntityType = EntityType.PROPERTY
    application_id: str
    address: Optional[str] = None
    appraised_value: Optional[float] = None
    purchase_price: Optional[float] = None


class CreditReport(BaseEntity):
    entity_type: EntityType = EntityType.CREDIT_REPORT
    customer_id: str
    bureau: str
    credit_score: Optional[int] = None
    pulled_at: datetime = Field(default_factory=datetime.utcnow)
    derogatory_marks: int = 0
    open_tradelines: int = 0
    credit_utilization: Optional[float] = None


class IncomeRecord(BaseEntity):
    entity_type: EntityType = EntityType.INCOME_RECORD
    application_id: str
    stated_income: Optional[float] = None
    verified_income: Optional[float] = None
    employment_type: Optional[str] = None
    income_confidence_score: Optional[float] = None
    payroll_verified: bool = False


class Document(BaseEntity):
    entity_type: EntityType = EntityType.DOCUMENT
    application_id: str
    doc_type: str
    storage_url: str
    authenticity_score: Optional[float] = None


class DecisionRecord(BaseEntity):
    entity_type: EntityType = EntityType.DECISION
    decision_id: DecisionId
    application_id: str
    outcome: DecisionOutcome
    mode: DecisionMode
    confidence: float
    payload: dict[str, Any] = Field(default_factory=dict)


# ────────────────────────────────────────────────────────────────────────────
# Event models — typed inbound events, one per EventType
# ────────────────────────────────────────────────────────────────────────────


class BaseEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    occurred_at: datetime = Field(default_factory=datetime.utcnow)
    received_at: datetime = Field(default_factory=datetime.utcnow)
    source_system: str = "unknown"
    application_id: Optional[str] = None
    customer_id: Optional[str] = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class LeadReceivedEvent(BaseEvent):
    event_type: EventType = EventType.LEAD_RECEIVED
    lead_source: str
    channel: Optional[str] = None
    utm_params: dict[str, Any] = Field(default_factory=dict)
    session_behavior: dict[str, Any] = Field(default_factory=dict)
    prior_inquiries: int = 0


class ApplicationSubmittedEvent(BaseEvent):
    event_type: EventType = EventType.APPLICATION_SUBMITTED
    loan_purpose: Optional[str] = None
    requested_amount: Optional[float] = None
    property_state: Optional[str] = None
    demographics: dict[str, Any] = Field(default_factory=dict)


class KYCCompletedEvent(BaseEvent):
    event_type: EventType = EventType.KYC_COMPLETED
    kyc_status: str
    identity_match_confidence: Optional[float] = None
    ambiguous_identity: bool = False


class IncomeDeclaredEvent(BaseEvent):
    event_type: EventType = EventType.INCOME_DECLARED
    stated_income: float
    employment_type: str
    multiple_income_sources: bool = False
    foreign_income: bool = False


class PayrollReceivedEvent(BaseEvent):
    event_type: EventType = EventType.PAYROLL_RECEIVED
    employer: Optional[str] = None
    gross_amount: float
    period_start: datetime
    period_end: datetime
    verified: bool = False


class TaxReturnUploadedEvent(BaseEvent):
    event_type: EventType = EventType.TAX_RETURN_UPLOADED
    tax_year: int
    total_income: float
    document_url: str


class BankStatementUploadedEvent(BaseEvent):
    event_type: EventType = EventType.BANK_STATEMENT_UPLOADED
    account_id: str
    period_start: datetime
    period_end: datetime
    document_url: str


class CreditPulledEvent(BaseEvent):
    event_type: EventType = EventType.CREDIT_PULLED
    bureau: str
    credit_score: Optional[int] = None
    payment_history: dict[str, Any] = Field(default_factory=dict)
    open_tradelines: int = 0
    derogatory_marks: int = 0
    credit_utilization: Optional[float] = None
    thin_file: bool = False
    active_bankruptcy: bool = False


class FraudSignalEvent(BaseEvent):
    event_type: EventType = EventType.FRAUD_SIGNAL
    signal_type: str
    fraud_score: Optional[float] = None
    device_fingerprint: Optional[str] = None
    ip_geolocation: Optional[str] = None
    velocity_signal: Optional[str] = None
    watchlist_match: bool = False
    synthetic_identity_flag: bool = False


class DocumentUploadedEvent(BaseEvent):
    event_type: EventType = EventType.DOCUMENT_UPLOADED
    doc_type: str
    storage_url: str
    authenticity_score: Optional[float] = None


class PropertyAppraisedEvent(BaseEvent):
    event_type: EventType = EventType.PROPERTY_APPRAISED
    address: str
    appraised_value: float
    purchase_price: Optional[float] = None
    appraisal_disputed: bool = False


class DecisionEmittedEvent(BaseEvent):
    event_type: EventType = EventType.DECISION_EMITTED
    decision_id: DecisionId
    outcome: DecisionOutcome
    mode: DecisionMode
    confidence: float = 1.0
    matched_clause: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    upstream_decision_ids: list[str] = Field(default_factory=list)


class HumanOverrideEvent(BaseEvent):
    event_type: EventType = EventType.HUMAN_OVERRIDE
    decision_id: DecisionId
    overrider: str
    original_outcome: DecisionOutcome
    new_outcome: DecisionOutcome
    justification: str


AnyEvent = Union[
    LeadReceivedEvent,
    ApplicationSubmittedEvent,
    KYCCompletedEvent,
    IncomeDeclaredEvent,
    PayrollReceivedEvent,
    TaxReturnUploadedEvent,
    BankStatementUploadedEvent,
    CreditPulledEvent,
    FraudSignalEvent,
    DocumentUploadedEvent,
    PropertyAppraisedEvent,
    DecisionEmittedEvent,
    HumanOverrideEvent,
]


_EVENT_MODEL_BY_TYPE: dict[EventType, type[BaseEvent]] = {
    EventType.LEAD_RECEIVED: LeadReceivedEvent,
    EventType.APPLICATION_SUBMITTED: ApplicationSubmittedEvent,
    EventType.KYC_COMPLETED: KYCCompletedEvent,
    EventType.INCOME_DECLARED: IncomeDeclaredEvent,
    EventType.PAYROLL_RECEIVED: PayrollReceivedEvent,
    EventType.TAX_RETURN_UPLOADED: TaxReturnUploadedEvent,
    EventType.BANK_STATEMENT_UPLOADED: BankStatementUploadedEvent,
    EventType.CREDIT_PULLED: CreditPulledEvent,
    EventType.FRAUD_SIGNAL: FraudSignalEvent,
    EventType.DOCUMENT_UPLOADED: DocumentUploadedEvent,
    EventType.PROPERTY_APPRAISED: PropertyAppraisedEvent,
    EventType.DECISION_EMITTED: DecisionEmittedEvent,
    EventType.HUMAN_OVERRIDE: HumanOverrideEvent,
}


# ────────────────────────────────────────────────────────────────────────────
# normalize_event — single entry point for raw → typed event
# ────────────────────────────────────────────────────────────────────────────


class NormalizationError(ValueError):
    """Raised when a raw event cannot be normalized into a typed model."""


def normalize_event(raw: dict[str, Any]) -> BaseEvent:
    """Coerce a raw inbound dict into a typed event model.

    The original dict is preserved on ``raw_payload`` so the trace layer
    can replay or audit the unmodified input — hard rule
    no_execution_without_trace."""

    if not isinstance(raw, dict):
        raise NormalizationError(f"event payload must be a dict, got {type(raw).__name__}")

    type_value = raw.get("event_type")
    if type_value is None:
        raise NormalizationError("event_type is required")

    try:
        event_type = EventType(type_value)
    except ValueError as err:
        raise NormalizationError(f"unknown event_type: {type_value!r}") from err

    cls = _EVENT_MODEL_BY_TYPE[event_type]

    payload = dict(raw)
    payload.setdefault("raw_payload", dict(raw))

    try:
        return cls.model_validate(payload)
    except ValidationError as err:
        raise NormalizationError(
            f"validation failed for {event_type.value}: {err.errors(include_url=False)}"
        ) from err
