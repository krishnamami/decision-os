"""Adverse Action Notice engine (RA-7B) — ECOA / Regulation B §1002.9.

When the final underwriting decision declines an application, ECOA (15 USC
1691(d)) requires a written adverse-action notice within 30 days, stating the
principal reasons. This engine turns the BLOCKING upstream decisions into a
structured notice payload with HMDA denial reason codes (Reg C 1–9) for the
workbench / downstream renderer.

Pure + DB-less (Architecture RULE 5/6): it receives the blocking decision types,
a ``rules`` dict (deadline window from the catalogue, RULE 4), and lender info,
and returns a JSON-serializable dict. It REUSES the canonical reason enum and the
HMDA code map from core.audit.adverse_action — no duplication.

Scope: produces notice DATA only (no email/PDF). Only deny/block triggers a
notice — escalate/recommend do NOT (those are not adverse actions).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from core.audit.adverse_action import (
    HMDA_DENIAL_CODE,
    HMDA_REASON_TEXT,
    AdverseActionReason,
)

# RULE 9 fallback only — the live value is "Adverse Action Notice Deadline"=30
# in regulatory_rules (Reg B §1002.9).
_DEFAULT_DAYS_MAX = 30
_MAX_REASONS = 4  # ECOA: a notice states up to 4 principal reasons.

# Which blocking decision implies which canonical ECOA reason. Mirrors the
# audit module's _DECISION_DEFAULT_REASONS but scoped to underwriting_decision's
# six upstreams (income / credit / fraud / dti / ltv / product).
DECISION_TO_REASON: dict[str, AdverseActionReason] = {
    "dti_calculation":     AdverseActionReason.EXCESSIVE_OBLIGATIONS,        # -> 1
    "income_verification": AdverseActionReason.INSUFFICIENT_INCOME,          # -> 1
    "credit_assessment":   AdverseActionReason.POOR_CREDIT_HISTORY,          # -> 3
    "ltv_assessment":      AdverseActionReason.INSUFFICIENT_COLLATERAL_VALUE,# -> 4
    "product_eligibility": AdverseActionReason.UNACCEPTABLE_PROPERTY_TYPE,   # -> 4
    "fraud_screening":     AdverseActionReason.SUSPECTED_FRAUD,              # -> 6
    "compliance_check":    AdverseActionReason.REGULATORY_RESTRICTION,       # -> 9
    "asset_verification":  AdverseActionReason.OTHER,                        # -> 9
}

ECOA_RIGHTS_STATEMENT = (
    "The Federal Equal Credit Opportunity Act prohibits creditors from "
    "discriminating against credit applicants on the basis of race, color, "
    "religion, national origin, sex, marital status, age (provided the "
    "applicant has the capacity to enter into a binding contract); because all "
    "or part of the applicant's income derives from any public assistance "
    "program; or because the applicant has in good faith exercised any right "
    "under the Consumer Credit Protection Act. The federal agency that "
    "administers compliance with this law concerning this creditor is the "
    "Consumer Financial Protection Bureau, 1700 G Street NW, Washington DC 20552."
)


class AdverseActionEngine:
    def __init__(self, rules: Optional[dict] = None):
        rules = rules or {}
        days = rules.get("adverse_action_days_max")
        try:
            self.days_max = int(days) if days is not None else _DEFAULT_DAYS_MAX
        except (TypeError, ValueError):
            self.days_max = _DEFAULT_DAYS_MAX

    def generate_notice(
        self,
        application_id: str,
        blocking_decisions: list[str],
        *,
        decision_date: Optional[str] = None,
        credit_bureau_used: bool = True,
        lender_info: Optional[dict] = None,
    ) -> dict:
        """Build the adverse-action notice payload from the decisions that
        blocked. Reasons are de-duplicated by HMDA code, capped at 4, sorted."""
        lender_info = lender_info or {}

        denial_reasons: list[dict] = []
        seen_codes: set[int] = set()
        for decision in blocking_decisions:
            reason = DECISION_TO_REASON.get(decision, AdverseActionReason.OTHER)
            code = HMDA_DENIAL_CODE.get(reason, 9)
            if code in seen_codes:
                continue
            seen_codes.add(code)
            denial_reasons.append({
                "hmda_code": code,
                "reason": HMDA_REASON_TEXT[code],
                "ecoa_reason": reason.value,
                "decision": decision,
            })
            if len(denial_reasons) >= _MAX_REASONS:
                break

        denial_reasons.sort(key=lambda d: d["hmda_code"])
        hmda_codes = [d["hmda_code"] for d in denial_reasons]

        base = date.fromisoformat(decision_date) if decision_date else date.today()
        deadline = base + timedelta(days=self.days_max)

        return {
            "notice_type": "ADVERSE_ACTION",
            "application_id": application_id,
            "decision_date": base.isoformat(),
            "notice_deadline": deadline.isoformat(),
            "days_to_notice": self.days_max,
            "denial_reasons": denial_reasons,
            "hmda_denial_codes": hmda_codes,
            "credit_bureau_used": credit_bureau_used,
            "fcra_disclosure_required": credit_bureau_used,
            "ecoa_rights_statement": ECOA_RIGHTS_STATEMENT,
            "lender_name": lender_info.get("name", ""),
            "lender_address": lender_info.get("address", ""),
            "citation": "15 USC 1691(d); Reg B §1002.9; HMDA Reg C 12 CFR 1003.4(a)(16)",
        }


__all__ = ["AdverseActionEngine", "DECISION_TO_REASON", "ECOA_RIGHTS_STATEMENT"]
