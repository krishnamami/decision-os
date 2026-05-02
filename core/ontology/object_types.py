from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────
# Link primitives
# ─────────────────────────────────────────────────────────────────────


class Cardinality(str, Enum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"
    ONE_TO_ONE_OPTIONAL = "one_to_one_optional"


class LinkDirection(str, Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"
    SELF_REFERENTIAL = "self_referential"


class Link(BaseModel):
    name: str
    target: str
    cardinality: Cardinality
    direction: LinkDirection = LinkDirection.OUTBOUND
    semantic_meaning: str


# How many edges of a given cardinality may exit a single source instance.
# Cardinality is read source→target: one_to_many means one source has many targets.
_MAX_LINKS_PER_SOURCE: dict[Cardinality, float] = {
    Cardinality.ONE_TO_ONE:          1,
    Cardinality.ONE_TO_ONE_OPTIONAL: 1,
    Cardinality.MANY_TO_ONE:         1,
    Cardinality.ONE_TO_MANY:         float("inf"),
    Cardinality.MANY_TO_MANY:        float("inf"),
}


# ─────────────────────────────────────────────────────────────────────
# Base ObjectType
# ─────────────────────────────────────────────────────────────────────


class ObjectType(BaseModel):
    """Domain-agnostic object-type descriptor.

    A subclass per business object type sets the class-level defaults
    (object_type_id, primary_key, properties, links,
    decisions_that_read_it). Instances are reusable singletons that the
    rest of the system queries for schema, link semantics, and
    decision-aware projections."""

    object_type_id: str
    semantic_definition: str = ""
    primary_key: str
    properties: dict[str, str] = Field(default_factory=dict)
    links: list[Link] = Field(default_factory=list)
    decisions_that_read_it: list[str] = Field(default_factory=list)

    # ── Decision-aware projection ────────────────────────────────────

    def to_context_bundle(
        self,
        instance: dict[str, Any],
        decision_id: str,
        fields: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Project a stored instance down to only the fields a given
        decision is authorized to read.

        Refuses to project for a decision that is not listed in
        ``decisions_that_read_it`` — keeps least-privilege at the data
        layer instead of relying on agent good behavior."""

        if decision_id not in self.decisions_that_read_it:
            raise PermissionError(
                f"decision {decision_id!r} does not read object type "
                f"{self.object_type_id!r}"
            )

        if fields is None:
            fields = list(self.properties.keys())

        unknown = [f for f in fields if f not in self.properties]
        if unknown:
            raise KeyError(
                f"unknown fields for {self.object_type_id!r}: {unknown}"
            )

        bundle = {f: instance.get(f) for f in fields}
        bundle["_object_type"] = self.object_type_id
        bundle["_primary_key"] = instance.get(self.primary_key)
        bundle["_decision_id"] = decision_id
        return bundle

    # ── Link validation ──────────────────────────────────────────────

    def link(self, name: str) -> Link:
        for link in self.links:
            if link.name == name:
                return link
        raise KeyError(
            f"no link {name!r} on {self.object_type_id!r}; "
            f"defined: {[l.name for l in self.links]}"
        )

    def validate_link(self, name: str, existing_link_count: int = 0) -> Link:
        """Confirm that adding one more outgoing edge of ``name`` from a
        single source instance would not exceed its cardinality.

        Returns the Link spec on success; raises ValueError on
        cardinality violation. Self-referential links additionally
        require the caller to ensure the source and target instances
        differ — this method cannot enforce that without the instance."""

        link = self.link(name)
        if existing_link_count < 0:
            raise ValueError("existing_link_count must be >= 0")

        max_allowed = _MAX_LINKS_PER_SOURCE[link.cardinality]
        if existing_link_count + 1 > max_allowed:
            raise ValueError(
                f"cardinality {link.cardinality.value} on "
                f"{self.object_type_id}.{name} allows at most "
                f"{int(max_allowed)} edge(s) per source; already at "
                f"{existing_link_count}"
            )
        return link


# ─────────────────────────────────────────────────────────────────────
# Lending object types — 8 concrete subclasses
#
# Class-level defaults mirror domains/lending/knowledge_base.json so a
# resolver in either direction (json↔python) is straightforward.
# ─────────────────────────────────────────────────────────────────────


class Applicant(ObjectType):
    object_type_id: str = "Applicant"
    semantic_definition: str = (
        "A natural person who has interacted with the lender — the WHO. "
        "Persists across applications and across time. One Applicant may "
        "submit many Applications, may co-apply with another Applicant, "
        "and accumulates multiple credit / income / fraud profiles. "
        "Re-applications reuse the Applicant; they do not create a new one."
    )
    primary_key: str = "applicant_id"
    properties: dict[str, str] = Field(default_factory=lambda: {
        "applicant_id": "string",
        "full_name": "string",
        "email": "string",
        "phone": "string",
        "date_of_birth": "date",
        "ssn_hash": "string",
        "kyc_status": "enum<verified|pending|rejected|manual_review>",
        "first_seen_at": "datetime",
        "last_seen_at": "datetime",
        # Lead-stage fields. lead_scoring runs before an Application
        # exists; the data lives on the Applicant until the
        # ApplicationSubmittedEvent fires.
        "lead_source": "string",
        "channel": "enum<digital|api_partner|branch|broker|call_center>",
        "utm_params": "object",
        "session_behavior": "object",
        "prior_inquiries": "integer",
        "ambiguous_identity": "boolean",
        "identity_match_confidence": "float",
        "applicant_dispute_flag": "boolean",
        "preferred_channel": "string",
    })
    links: list[Link] = Field(default_factory=lambda: [
        Link(
            name="submits",
            target="Application",
            cardinality=Cardinality.ONE_TO_MANY,
            direction=LinkDirection.OUTBOUND,
            semantic_meaning="An applicant submits many applications over their lifetime. Each application is a fresh request, never a mutation of a prior one.",
        ),
        Link(
            name="has_credit_profile",
            target="CreditProfile",
            cardinality=Cardinality.ONE_TO_MANY,
            direction=LinkDirection.OUTBOUND,
            semantic_meaning="One CreditProfile per bureau pull. Old profiles are retained; never overwritten.",
        ),
        Link(
            name="has_income_profile",
            target="IncomeProfile",
            cardinality=Cardinality.ONE_TO_MANY,
            direction=LinkDirection.OUTBOUND,
            semantic_meaning="One IncomeProfile per verification event.",
        ),
        Link(
            name="has_fraud_profile",
            target="FraudProfile",
            cardinality=Cardinality.ONE_TO_MANY,
            direction=LinkDirection.OUTBOUND,
            semantic_meaning="One FraudProfile per screening run. Identity does not reset across applications.",
        ),
        Link(
            name="co_applies_with",
            target="Applicant",
            cardinality=Cardinality.MANY_TO_MANY,
            direction=LinkDirection.SELF_REFERENTIAL,
            semantic_meaning="Joint applicants on a single Application. Symmetric — if A co-applies with B, B co-applies with A.",
        ),
    ])
    decisions_that_read_it: list[str] = Field(default_factory=lambda: [
        "lead_scoring",
        "income_verification",
        "credit_assessment",
        "fraud_screening",
        "compliance_check",
        "underwriting_decision",
        "approval_routing",
    ])


class Application(ObjectType):
    object_type_id: str = "Application"
    semantic_definition: str = (
        "A specific loan request made by an Applicant against a specific "
        "Property at a specific moment — the WHAT THEY ARE ASKING FOR NOW. "
        "Has its own lifecycle. A re-application creates a NEW Application; "
        "the prior one is closed, not edited."
    )
    primary_key: str = "application_id"
    properties: dict[str, str] = Field(default_factory=lambda: {
        "application_id": "string",
        "applicant_id": "string",
        "status": "enum<intake|underwriting|approved|conditional|declined|withdrawn|closed>",
        "loan_purpose": "enum<purchase|rate_term_refinance|cash_out_refinance|construction>",
        "requested_amount": "float",
        "channel": "enum<digital|api_partner|branch|broker|call_center>",
        "property_state": "string",
        "submitted_at": "datetime",
        "decision_due_by": "datetime",
    })
    links: list[Link] = Field(default_factory=lambda: [
        Link(
            name="submitted_by",
            target="Applicant",
            cardinality=Cardinality.MANY_TO_ONE,
            direction=LinkDirection.INBOUND,
            semantic_meaning="The primary applicant of record. Co-applicants are reached via Applicant.co_applies_with.",
        ),
        Link(
            name="secured_by",
            target="Property",
            cardinality=Cardinality.ONE_TO_ONE,
            direction=LinkDirection.OUTBOUND,
            semantic_meaning="The subject property collateralizing this loan.",
        ),
        Link(
            name="requests",
            target="Loan",
            cardinality=Cardinality.ONE_TO_ONE,
            direction=LinkDirection.OUTBOUND,
            semantic_meaning="The loan terms being requested or offered for this application.",
        ),
        Link(
            name="evaluated_by",
            target="Decision",
            cardinality=Cardinality.ONE_TO_MANY,
            direction=LinkDirection.OUTBOUND,
            semantic_meaning="The 12 lending decisions evaluated for this application; see decisions.yaml.",
        ),
        Link(
            name="governed_by",
            target="ComplianceRecord",
            cardinality=Cardinality.ONE_TO_ONE,
            direction=LinkDirection.OUTBOUND,
            semantic_meaning="Compliance posture for this application — HMDA, fair-lending, TRID timing. Owned by the Application; never shared.",
        ),
    ])
    decisions_that_read_it: list[str] = Field(default_factory=lambda: [
        "lead_scoring",
        "income_verification",
        "credit_assessment",
        "fraud_screening",
        "compliance_check",
        "dti_calculation",
        "ltv_assessment",
        "product_eligibility",
        "rate_pricing",
        "underwriting_decision",
        "approval_routing",
        "closing_readiness",
    ])


class Property(ObjectType):
    object_type_id: str = "Property"
    semantic_definition: str = (
        "The real-property asset securing the loan. Belongs to a single "
        "Application — different applications get different Property "
        "objects, even at the same address."
    )
    primary_key: str = "property_id"
    properties: dict[str, str] = Field(default_factory=lambda: {
        "property_id": "string",
        "application_id": "string",
        "address": "string",
        "property_type": "enum<single_family|condo|townhouse|multi_unit|manufactured>",
        "occupancy": "enum<primary|secondary|investment>",
        "appraised_value": "float",
        "purchase_price": "float",
        "down_payment": "float",
        "title_status": "enum<clear|defect|pending>",
        "lien_status": "string",
    })
    links: list[Link] = Field(default_factory=lambda: [
        Link(
            name="secures",
            target="Application",
            cardinality=Cardinality.ONE_TO_ONE,
            direction=LinkDirection.INBOUND,
            semantic_meaning="Inverse of Application.secured_by.",
        ),
    ])
    decisions_that_read_it: list[str] = Field(default_factory=lambda: [
        "ltv_assessment",
        "underwriting_decision",
        "closing_readiness",
    ])


class Loan(ObjectType):
    object_type_id: str = "Loan"
    semantic_definition: str = (
        "The loan product and terms requested or offered. Tightly coupled "
        "to one Application — a new Application creates a new Loan."
    )
    primary_key: str = "loan_id"
    properties: dict[str, str] = Field(default_factory=lambda: {
        "loan_id": "string",
        "application_id": "string",
        "loan_type": "enum<conforming|jumbo|fha|va|usda|non_qm>",
        "principal_amount": "float",
        "term_months": "integer",
        "lock_period": "integer",
        "interest_rate": "float",
        "llpa": "float",
        "ltv_ratio": "float",
        "dti_ratio": "float",
        "eligible_products": "list<string>",
    })
    links: list[Link] = Field(default_factory=lambda: [
        Link(
            name="requested_in",
            target="Application",
            cardinality=Cardinality.ONE_TO_ONE,
            direction=LinkDirection.INBOUND,
            semantic_meaning="Inverse of Application.requests.",
        ),
    ])
    decisions_that_read_it: list[str] = Field(default_factory=lambda: [
        "product_eligibility",
        "rate_pricing",
        "dti_calculation",
        "ltv_assessment",
        "underwriting_decision",
        "approval_routing",
        "closing_readiness",
    ])


class CreditProfile(ObjectType):
    object_type_id: str = "CreditProfile"
    semantic_definition: str = (
        "Snapshot of an Applicant's credit at a point in time, from a "
        "specific bureau. Immutable — a re-pull creates a new "
        "CreditProfile rather than overwriting. Belongs to the Applicant "
        "so re-applications can reuse a recent pull within retention."
    )
    primary_key: str = "credit_profile_id"
    properties: dict[str, str] = Field(default_factory=lambda: {
        "credit_profile_id": "string",
        "applicant_id": "string",
        "bureau": "enum<experian|equifax|transunion|tri_merge>",
        "pulled_at": "datetime",
        "credit_score": "integer",
        "credit_band": "enum<super_prime|prime|near_prime|subprime|deep_subprime|thin_file>",
        "derogatory_marks": "integer",
        "open_tradelines": "integer",
        "credit_utilization": "float",
        "payment_history": "object",
        "thin_file": "boolean",
        "active_bankruptcy": "boolean",
        "foreclosure_last_36_months": "boolean",
        "no_derogatory_last_24_months": "boolean",
    })
    links: list[Link] = Field(default_factory=lambda: [
        Link(
            name="belongs_to",
            target="Applicant",
            cardinality=Cardinality.MANY_TO_ONE,
            direction=LinkDirection.INBOUND,
            semantic_meaning="The applicant this snapshot belongs to.",
        ),
    ])
    decisions_that_read_it: list[str] = Field(default_factory=lambda: [
        "credit_assessment",
        "ltv_assessment",
        "product_eligibility",
        "rate_pricing",
        "underwriting_decision",
    ])


class IncomeProfile(ObjectType):
    object_type_id: str = "IncomeProfile"
    semantic_definition: str = (
        "Verified income snapshot for an Applicant, optionally scoped to "
        "a specific Application. Belongs to the Applicant so "
        "re-applications can carry forward a recent verification within "
        "retention; the application_id is recorded for trace, not ownership."
    )
    primary_key: str = "income_profile_id"
    properties: dict[str, str] = Field(default_factory=lambda: {
        "income_profile_id": "string",
        "applicant_id": "string",
        "application_id": "string",
        "stated_income": "float",
        "verified_income": "float",
        "employment_type": "enum<salaried|self_employed|contractor|retired|unemployed|other>",
        "payroll_verified": "boolean",
        "income_confidence_score": "float",
        "income_discrepancy_pct": "float",
        "multiple_income_sources": "boolean",
        "foreign_income": "boolean",
        "verified_at": "datetime",
    })
    links: list[Link] = Field(default_factory=lambda: [
        Link(
            name="belongs_to",
            target="Applicant",
            cardinality=Cardinality.MANY_TO_ONE,
            direction=LinkDirection.INBOUND,
            semantic_meaning="The applicant whose income this snapshot represents.",
        ),
        Link(
            name="scoped_to",
            target="Application",
            cardinality=Cardinality.MANY_TO_ONE,
            direction=LinkDirection.OUTBOUND,
            semantic_meaning="Income verification is usually triggered by an Application, but the result attaches to the Applicant.",
        ),
    ])
    decisions_that_read_it: list[str] = Field(default_factory=lambda: [
        "income_verification",
        "dti_calculation",
        "product_eligibility",
        "underwriting_decision",
    ])


class FraudProfile(ObjectType):
    object_type_id: str = "FraudProfile"
    semantic_definition: str = (
        "Identity / fraud signals collected for an Applicant. Belongs to "
        "the Applicant because identity does not reset across "
        "applications — fraud signals on application N+1 must be informed "
        "by signals seen on application N."
    )
    primary_key: str = "fraud_profile_id"
    properties: dict[str, str] = Field(default_factory=lambda: {
        "fraud_profile_id": "string",
        "applicant_id": "string",
        "generated_at": "datetime",
        "fraud_score": "float",
        "identity_match_confidence": "float",
        "document_authenticity_score": "float",
        "watchlist_match": "boolean",
        "synthetic_identity_flag": "boolean",
        "device_fingerprint": "string",
        "ip_geolocation": "string",
        "velocity_signals": "list<string>",
    })
    links: list[Link] = Field(default_factory=lambda: [
        Link(
            name="belongs_to",
            target="Applicant",
            cardinality=Cardinality.MANY_TO_ONE,
            direction=LinkDirection.INBOUND,
            semantic_meaning="The applicant this fraud snapshot belongs to.",
        ),
    ])
    decisions_that_read_it: list[str] = Field(default_factory=lambda: [
        "fraud_screening",
        "compliance_check",
        "underwriting_decision",
    ])


class ComplianceRecord(ObjectType):
    object_type_id: str = "ComplianceRecord"
    semantic_definition: str = (
        "Compliance posture for a single Application — HMDA, ECOA / "
        "fair-lending, state-specific rules, TRID timing. Owned by the "
        "Application; never shared across applications because the "
        "regulatory snapshot is application-specific."
    )
    primary_key: str = "compliance_record_id"
    properties: dict[str, str] = Field(default_factory=lambda: {
        "compliance_record_id": "string",
        "application_id": "string",
        "hmda_fields": "object",
        "all_hmda_fields_complete": "boolean",
        "fair_lending_violation": "boolean",
        "missing_required_disclosures": "boolean",
        "state_rules_passed": "boolean",
        "cd_timing_compliant": "boolean",
        "closing_disclosure_sent_at": "datetime",
        "regulatory_ambiguity": "boolean",
        "mixed_jurisdiction": "boolean",
        "recorded_at": "datetime",
    })
    links: list[Link] = Field(default_factory=lambda: [
        Link(
            name="governs",
            target="Application",
            cardinality=Cardinality.ONE_TO_ONE,
            direction=LinkDirection.INBOUND,
            semantic_meaning="Inverse of Application.governed_by.",
        ),
    ])
    decisions_that_read_it: list[str] = Field(default_factory=lambda: [
        "compliance_check",
        "underwriting_decision",
        "closing_readiness",
    ])


LENDING_OBJECT_TYPES: dict[str, ObjectType] = {
    cls().object_type_id: cls()
    for cls in (
        Applicant,
        Application,
        Property,
        Loan,
        CreditProfile,
        IncomeProfile,
        FraudProfile,
        ComplianceRecord,
    )
}
