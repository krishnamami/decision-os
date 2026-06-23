"""Adverse action notice generator — ECOA / FCRA §615.

When the platform declines or escalates an application without
approval, ECOA requires the applicant receive a written notice within
30 days. The notice must include:

  - Applicant identification
  - The action taken (decline / counter-offer / incomplete)
  - The principal reasons (from a closed list of reason codes)
  - For credit-bureau-driven actions: name + address of the bureau,
    plus the FCRA "you have the right to a free copy of your report"
    disclosure
  - The right to request the specific reasons in writing (60 days)
  - The ECOA non-discrimination notice

This module produces a structured notice from an AuditRecord plus
the corresponding DecisionTrace and Applicant value. The notice is
serializable JSON; the rendering layer (PDF / mail / portal) lives
downstream and isn't in scope here.

PRD §19 TIER 4: "Auto-generate from decline traces. ECOA requires a
notice within 30 days of adverse action."
"""
from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from core.normalizer.models import DecisionOutcome
from core.trace.trace_schema import DecisionTrace

from .schema import AuditRecord, CheckStatus


# ─────────────────────────────────────────────────────────────────────
# Canonical ECOA reason codes (subset).
#
# The full Regulation B sample form lists ~30 reason codes; we map the
# patterns the persona policies actually emit (DTI ratio, LTV ratio,
# credit score band, employment, fraud, compliance) to the closest
# canonical entries. Reason codes are stable across years; the wording
# changes but the codes do not.
# ─────────────────────────────────────────────────────────────────────


class AdverseActionReason(str, Enum):
    EXCESSIVE_OBLIGATIONS         = "excessive_obligations"          # DTI too high
    INSUFFICIENT_INCOME           = "insufficient_income"            # income low / unverified
    INSUFFICIENT_COLLATERAL_VALUE = "insufficient_collateral_value"  # LTV too high
    UNACCEPTABLE_PROPERTY_TYPE    = "unacceptable_property_type"
    POOR_CREDIT_HISTORY           = "poor_credit_history"            # derog / bankruptcy
    LIMITED_CREDIT_EXPERIENCE     = "limited_credit_experience"      # thin file
    LENGTH_OF_EMPLOYMENT          = "length_of_employment"
    APPLICATION_INCOMPLETE        = "application_incomplete"
    UNABLE_TO_VERIFY_INFORMATION  = "unable_to_verify_information"
    SUSPECTED_FRAUD               = "suspected_fraud"                # fraud_screening block
    REGULATORY_RESTRICTION        = "regulatory_restriction"         # compliance_check block
    NO_CREDIT_FILE                = "no_credit_file"
    OTHER                         = "other"


class ActionTaken(str, Enum):
    DECLINED         = "declined"
    COUNTER_OFFER    = "counter_offer"
    INCOMPLETE       = "incomplete"
    PENDING          = "pending"


# Policy-reason fragment → canonical reason code.
_POLICY_REASON_TO_CODE: dict[str, AdverseActionReason] = {
    "fraud_block_stops_pipeline":          AdverseActionReason.SUSPECTED_FRAUD,
    "compliance_block_stops_closing":      AdverseActionReason.REGULATORY_RESTRICTION,
    "fair_lending_violation":              AdverseActionReason.REGULATORY_RESTRICTION,
    "missing_required_disclosures":        AdverseActionReason.APPLICATION_INCOMPLETE,
    "contamination_guard":                 AdverseActionReason.UNABLE_TO_VERIFY_INFORMATION,
    "active_bankruptcy":                   AdverseActionReason.POOR_CREDIT_HISTORY,
    "foreclosure_last_36_months":          AdverseActionReason.POOR_CREDIT_HISTORY,
    "thin_file":                           AdverseActionReason.LIMITED_CREDIT_EXPERIENCE,
    "ltv":                                 AdverseActionReason.INSUFFICIENT_COLLATERAL_VALUE,
    "dti":                                 AdverseActionReason.EXCESSIVE_OBLIGATIONS,
    "verified_income":                     AdverseActionReason.INSUFFICIENT_INCOME,
    "income_confidence_score":             AdverseActionReason.UNABLE_TO_VERIFY_INFORMATION,
}


# Decision_type → which canonical reasons are typical for that block.
_DECISION_DEFAULT_REASONS: dict[str, AdverseActionReason] = {
    "credit_assessment":     AdverseActionReason.POOR_CREDIT_HISTORY,
    "income_verification":   AdverseActionReason.INSUFFICIENT_INCOME,
    "fraud_screening":       AdverseActionReason.SUSPECTED_FRAUD,
    "compliance_check":      AdverseActionReason.REGULATORY_RESTRICTION,
    "dti_calculation":       AdverseActionReason.EXCESSIVE_OBLIGATIONS,
    "ltv_assessment":        AdverseActionReason.INSUFFICIENT_COLLATERAL_VALUE,
    "product_eligibility":   AdverseActionReason.UNACCEPTABLE_PROPERTY_TYPE,
    "asset_verification":    AdverseActionReason.OTHER,
    "underwriting_decision": AdverseActionReason.OTHER,
    "closing_readiness":     AdverseActionReason.REGULATORY_RESTRICTION,
}


# ─────────────────────────────────────────────────────────────────────
# HMDA / Regulation C denial reason codes (1–9). Each canonical ECOA
# reason maps to the closest HMDA code so the adverse-action notice can
# carry the numeric codes regulators expect on the LAR. (12 CFR 1003.4(a)(16).)
# ─────────────────────────────────────────────────────────────────────
HMDA_REASON_TEXT: dict[int, str] = {
    1: "Debt-to-income ratio",
    2: "Employment history",
    3: "Credit history",
    4: "Collateral",
    5: "Insufficient cash (down payment, closing costs)",
    6: "Unverifiable information",
    7: "Credit application incomplete",
    8: "Mortgage insurance denied",
    9: "Other",
}

HMDA_DENIAL_CODE: dict[AdverseActionReason, int] = {
    AdverseActionReason.EXCESSIVE_OBLIGATIONS:         1,
    AdverseActionReason.INSUFFICIENT_INCOME:           1,
    AdverseActionReason.LENGTH_OF_EMPLOYMENT:          2,
    AdverseActionReason.POOR_CREDIT_HISTORY:           3,
    AdverseActionReason.LIMITED_CREDIT_EXPERIENCE:     3,
    AdverseActionReason.NO_CREDIT_FILE:                3,
    AdverseActionReason.INSUFFICIENT_COLLATERAL_VALUE: 4,
    AdverseActionReason.UNACCEPTABLE_PROPERTY_TYPE:    4,
    AdverseActionReason.UNABLE_TO_VERIFY_INFORMATION:  6,
    AdverseActionReason.SUSPECTED_FRAUD:               6,
    AdverseActionReason.APPLICATION_INCOMPLETE:        7,
    AdverseActionReason.REGULATORY_RESTRICTION:        9,
    AdverseActionReason.OTHER:                         9,
}


def hmda_codes_for(reasons: list[AdverseActionReason]) -> list[int]:
    """Distinct HMDA denial codes for a list of canonical reasons, sorted."""
    codes: list[int] = []
    for r in reasons:
        code = HMDA_DENIAL_CODE.get(r, 9)
        if code not in codes:
            codes.append(code)
    return sorted(codes)


class AdverseActionNotice(BaseModel):
    """Structured notice. Renderer (PDF / mail / portal) consumes
    this. JSON-serializable so it persists alongside the audit record
    and ships to downstream queues unchanged."""

    notice_id: Optional[str] = None
    audit_id: str
    decision_id: str
    application_id: str
    applicant_id: Optional[str] = None
    applicant_name: Optional[str] = None

    action: ActionTaken
    action_date: datetime = Field(default_factory=datetime.utcnow)
    notice_due_by: datetime  # action_date + 30 days

    decision_type: str
    decision_output: DecisionOutcome
    reasons: list[AdverseActionReason]
    reason_descriptions: list[str] = Field(default_factory=list)
    hmda_denial_codes: list[int] = Field(default_factory=list)  # Reg C 1–9

    # FCRA disclosures — required when a credit bureau report drove
    # the decision. AuditRecord.data_sources_used carries the signal.
    bureau_used: Optional[str] = None
    fcra_required: bool = False

    # Standard ECOA boilerplate the renderer pastes verbatim.
    ecoa_statement: str = (
        "The Federal Equal Credit Opportunity Act prohibits creditors "
        "from discriminating against credit applicants on the basis of "
        "race, color, religion, national origin, sex, marital status, "
        "age (provided the applicant has the capacity to enter into a "
        "binding contract); because all or part of the applicant's "
        "income derives from any public assistance program; or because "
        "the applicant has in good faith exercised any right under the "
        "Consumer Credit Protection Act."
    )


# ─────────────────────────────────────────────────────────────────────
# Generator
# ─────────────────────────────────────────────────────────────────────


def is_adverse_action(record: AuditRecord) -> bool:
    """Adverse action under ECOA = a decline / counter-offer / failure
    to act on the requested terms. We treat any of:
      - decision_output == BLOCK
      - decision_output == ESCALATE on the final underwriting/closing
        decisions (those that gate funding)
      - overall_status == FAIL on a compliance-relevant decision

    Allow + recommend are NOT adverse actions; recommend goes to human
    approval which (per fair_lending semantics) typically funds."""

    if record.decision_output == DecisionOutcome.BLOCK:
        return True
    if record.decision_output == DecisionOutcome.ESCALATE and record.decision_type in (
        "underwriting_decision", "closing_readiness", "approval_routing",
    ):
        return True
    if record.overall_status == CheckStatus.FAIL and record.decision_type in (
        "compliance_check", "fraud_screening",
    ):
        return True
    return False


def generate_notice(
    record: AuditRecord,
    trace: DecisionTrace,
    *,
    applicant_value: Optional[dict[str, Any]] = None,
    days_max: int = 30,
) -> AdverseActionNotice:
    """Build an AdverseActionNotice from an AuditRecord + DecisionTrace.
    Caller is responsible for asserting `is_adverse_action(record)`
    before invoking; the function generates a notice regardless of
    whether the underlying decision actually qualifies.

    ``days_max`` is the notice deadline window (Reg B §1002.9 = 30 days); the
    caller should pass the catalogue value (regulatory_rules) rather than rely
    on the default, which is the RULE 9 safety net only."""

    reasons: list[AdverseActionReason] = []
    descriptions: list[str] = []

    # Walk policy_reasons on the trace — those are the strongest
    # signal of what tipped the decision. Map known fragments to
    # canonical codes.
    seen: set[AdverseActionReason] = set()
    for reason_str in (trace.policy_reasons or []):
        for fragment, code in _POLICY_REASON_TO_CODE.items():
            if fragment in reason_str.lower():
                if code not in seen:
                    reasons.append(code)
                    descriptions.append(reason_str)
                    seen.add(code)
                break

    # Audit-check fails contribute their own canonical reasons.
    if record.compliance_status == CheckStatus.FAIL:
        if AdverseActionReason.REGULATORY_RESTRICTION not in seen:
            reasons.append(AdverseActionReason.REGULATORY_RESTRICTION)
            descriptions.append(
                f"Compliance check failed (consent={record.consent_status.value})."
            )
            seen.add(AdverseActionReason.REGULATORY_RESTRICTION)
    if record.security_status == CheckStatus.FAIL:
        if AdverseActionReason.UNABLE_TO_VERIFY_INFORMATION not in seen:
            reasons.append(AdverseActionReason.UNABLE_TO_VERIFY_INFORMATION)
            descriptions.append("Security checks failed during processing.")
            seen.add(AdverseActionReason.UNABLE_TO_VERIFY_INFORMATION)

    # Fall back to the decision-type default if we still have nothing.
    if not reasons:
        default = _DECISION_DEFAULT_REASONS.get(
            record.decision_type, AdverseActionReason.OTHER
        )
        reasons.append(default)
        descriptions.append(
            f"Application declined at {record.decision_type}."
        )

    # Action classification
    if record.decision_output == DecisionOutcome.BLOCK:
        action = ActionTaken.DECLINED
    elif record.decision_output == DecisionOutcome.ESCALATE:
        action = ActionTaken.PENDING
    else:
        action = ActionTaken.INCOMPLETE

    # FCRA — was a credit bureau used?
    bureau_used: Optional[str] = None
    fcra_required = False
    if "credit_bureau" in (record.data_sources_used or []):
        fcra_required = True
        bureau_used = "credit_bureau"  # Real wiring fills bureau name from CreditProfile.

    # Applicant info
    applicant_id = None
    applicant_name = None
    if isinstance(applicant_value, dict):
        applicant_id = applicant_value.get("applicant_id")
        first = applicant_value.get("first_name") or ""
        last = applicant_value.get("last_name") or ""
        full = (first + " " + last).strip()
        applicant_name = full or None

    action_date = record.timestamp
    notice_due_by = action_date + timedelta(days=days_max)

    return AdverseActionNotice(
        audit_id=str(record.audit_id),
        decision_id=str(record.decision_id),
        application_id=record.application_id,
        applicant_id=applicant_id,
        applicant_name=applicant_name,
        action=action,
        action_date=action_date,
        notice_due_by=notice_due_by,
        decision_type=record.decision_type,
        decision_output=record.decision_output,
        reasons=reasons,
        reason_descriptions=descriptions,
        hmda_denial_codes=hmda_codes_for(reasons),
        bureau_used=bureau_used,
        fcra_required=fcra_required,
    )


__all__ = [
    "ActionTaken",
    "AdverseActionNotice",
    "AdverseActionReason",
    "HMDA_DENIAL_CODE",
    "HMDA_REASON_TEXT",
    "hmda_codes_for",
    "generate_notice",
    "is_adverse_action",
]
