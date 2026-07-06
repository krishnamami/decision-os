"""
Persona -> conditions_library code mapping (CN-B).

When a persona produces BLOCK/ESCALATE, map it to the most-specific
conditions_library code using the signals in the decision's boundary_rule
(e.g. "ltv=1.000, ... max_allowable=0.95 -> block") + optional reasoning['signals'],
falling back to the persona's default_block. Every code below exists in
conditions_library (verified). underwriting_decision / approval_routing /
rate_pricing are excluded -- their BLOCK is a decline (adverse action), not a
clearable condition.
"""
import re
from typing import Optional

PERSONA_CONDITION_MAP: dict[str, dict[str, str]] = {
    "ltv_assessment":            {"appraisal_gap": "COLLATERAL_APPRAISAL_GAP", "high_ltv": "COLLATERAL_HIGH_LTV", "default_block": "COLLATERAL_LTV_REVIEW"},
    "credit_assessment":         {"bankruptcy": "CREDIT_LOE_BANKRUPTCY", "foreclosure": "CREDIT_LOE_FORECLOSURE", "default_block": "PRODUCT_INELIGIBLE_BORROWER"},
    "income_verification":       {"discrepancy": "INCOME_DISCREPANCY_EXPLANATION", "default_block": "INCOME_VOE_REQUIRED"},
    "employment_reconciliation": {"gap": "EMPLOYMENT_GAP_LOE", "mismatch": "EMPLOYMENT_MISMATCH_EXPLANATION", "default_block": "EMPLOYMENT_VOE_CURRENT"},
    "fraud_screening":           {"income_mismatch": "FRAUD_INCOME_MISMATCH", "employer_mismatch": "FRAUD_EMPLOYER_MISMATCH", "default_block": "FRAUD_IDENTITY_REVIEW"},
    "compliance_check":          {"hmda": "COMPLIANCE_HMDA_COMPLETE", "trid": "COMPLIANCE_TRID_DISCLOSURE", "fair_lending": "COMPLIANCE_FAIR_LENDING_REVIEW", "default_block": "COMPLIANCE_FAIR_LENDING_REVIEW"},
    "asset_verification":        {"large_deposit": "ASSET_LARGE_DEPOSIT", "seasoning": "ASSET_SEASONING", "default_block": "ASSET_INSUFFICIENT"},
    "product_eligibility":       {"conforming": "PRODUCT_CONFORMING_LIMIT", "default_block": "PRODUCT_INELIGIBLE_BORROWER"},
    "closing_readiness":         {"title": "CLOSING_TITLE_COMMITMENT", "cd_timing": "CLOSING_CD_TIMING", "default_block": "CLOSING_CD_TIMING"},
    "dti_calculation":           {"default_block": "PRODUCT_DTI_EXCEPTION"},
}

CONDITION_EXCLUDED_DECISIONS = {"underwriting_decision", "approval_routing", "rate_pricing"}


def _ltv(text: str) -> Optional[float]:
    m = re.search(r"ltv\s*[=>]?\s*([0-9]*\.?[0-9]+)", text)
    return float(m.group(1)) if m else None


def select_condition_code(decision_id: str, boundary_rule: Optional[str] = None,
                          signals: Optional[dict] = None) -> Optional[str]:
    """Most-specific conditions_library code for a persona BLOCK/ESCALATE, or None
    for excluded/unmapped personas. Detection reads boundary_rule (lowercased);
    default_block fallback."""
    if decision_id in CONDITION_EXCLUDED_DECISIONS:
        return None
    persona = PERSONA_CONDITION_MAP.get(decision_id)
    if not persona:
        return None
    t = (boundary_rule or "").lower()

    def has(*subs: str) -> bool:
        return any(s in t for s in subs)

    if decision_id == "ltv_assessment":
        if has("appraisal", "appraised", "gap"):
            return persona["appraisal_gap"]
        ltv = _ltv(t)
        if has("ltv > 97") or (ltv is not None and ltv >= 0.97):
            return persona["high_ltv"]
    elif decision_id == "credit_assessment":
        if has("active_bankruptcy=true", "bankruptcy=true"):
            return persona["bankruptcy"]
        if has("foreclosure=true"):
            return persona["foreclosure"]
    elif decision_id == "income_verification":
        if has("discrepanc"):
            return persona["discrepancy"]
    elif decision_id == "employment_reconciliation":
        if has("gap"):
            return persona["gap"]
        if has("mismatch"):
            return persona["mismatch"]
    elif decision_id == "fraud_screening":
        if has("income_mismatch", "income mismatch"):
            return persona["income_mismatch"]
        if has("employer"):
            return persona["employer_mismatch"]
    elif decision_id == "compliance_check":
        if has("hmda_complete=false", "hmda=false"):
            return persona["hmda"]
        if has("fair_lending_violation=true", "fair_lending=true"):
            return persona["fair_lending"]
        if has("trid", "cd_timing", "missing_di", "disclosure"):
            return persona["trid"]
    elif decision_id == "asset_verification":
        if has("large_deposit", "large deposit"):
            return persona["large_deposit"]
        if has("seasoning"):
            return persona["seasoning"]
    elif decision_id == "product_eligibility":
        if has("conforming"):
            return persona["conforming"]
    elif decision_id == "closing_readiness":
        if has("title_defect", "title_clear=false"):
            return persona["title"]
        if has("cd_timing", "cd timing"):
            return persona["cd_timing"]

    return persona.get("default_block")


__all__ = ["PERSONA_CONDITION_MAP", "CONDITION_EXCLUDED_DECISIONS", "select_condition_code"]
