"""HMDA Loan/Application Register (LAR) record generator (RA-7C) — Reg C,
12 CFR Part 1003.

HMDA requires one LAR record per application capturing loan data, the action
taken, and applicant demographic data. CRITICAL (ECOA / 12 CFR 1002.6(b)(9)):
demographic data (ethnicity / race / sex / age) is COLLECTED AND REPORTED but
MUST NEVER influence the underwriting decision. This generator only assembles
the record AFTER the outcome is decided; it never feeds a decision.

Pure + DB-less (RULE 5/6): it takes a flat ``fields`` dict (sourced from
vw_hmda_reporting + entity_states by the enricher) plus the decided outcome and
the adverse-action payload (RA-7B), and returns a JSON-serializable LAR record.
Demographic codes follow the FFIEC HMDA spec; absent values default to the
official "information not provided" codes.
"""
from __future__ import annotations

from typing import Any, Optional

# Decided outcome -> HMDA action_taken code (12 CFR 1003.4(a)(8)).
ACTION_TAKEN_MAP = {
    "allow":      1,   # Loan originated
    "recommend":  1,   # Originated (approve w/ conditions)
    "approve":    1,
    "escalate":   2,   # Application approved but not accepted (pending review)
    "block":      3,   # Application denied
    "deny":       3,
    "withdraw":   4,   # Application withdrawn
    "incomplete": 5,   # File closed for incompleteness
}

# FFIEC "information not provided" defaults (NOT the prompt's 5/7/3, which are
# not the official codes). Ethnicity 3 / Race 6 / Sex 3.
_ETHNICITY_NA = 3
_RACE_NA = 6
_SEX_NA = 3


def _ethnicity_code(v: Any) -> int:
    s = str(v or "").lower()
    if not s:
        return _ETHNICITY_NA
    if "hispanic" in s or "latino" in s:
        return 2 if "not" in s else 1
    return _ETHNICITY_NA


def _race_code(v: Any) -> int:
    s = str(v or "").lower()
    if not s:
        return _RACE_NA
    if "american indian" in s or "alaska" in s:
        return 1
    if "asian" in s:
        return 2
    if "black" in s or "african" in s:
        return 3
    if "pacific" in s or "hawaiian" in s:
        return 4
    if "white" in s:
        return 5
    return _RACE_NA


def _sex_code(v: Any) -> int:
    s = str(v or "").lower()
    if not s:
        return _SEX_NA
    if "female" in s:
        return 2
    if "male" in s:
        return 1
    return _SEX_NA


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class HMDALARGenerator:
    """Assemble a HMDA LAR record. Stateless; one call per application."""

    def generate_lar_record(
        self,
        application_id: str,
        fields: dict,
        *,
        outcome: str,
        adverse_action: Optional[dict] = None,
        tenant_id: Optional[str] = None,
        decision_date: Optional[str] = None,
    ) -> dict:
        fields = fields or {}
        action_taken = ACTION_TAKEN_MAP.get((outcome or "").lower(), 5)

        # Denial reasons only when denied (action 3), carried from RA-7B.
        denial_reasons: list[int] = []
        if action_taken == 3 and adverse_action:
            denial_reasons = list(adverse_action.get("hmda_denial_codes", []))[:4]

        monthly_income = _num(fields.get("qualifying_monthly"))
        applicant_income = round(monthly_income * 12, 2) if monthly_income else None

        return {
            "application_id":      application_id,
            "tenant_id":           tenant_id,
            "action_taken":        action_taken,
            "action_taken_date":   decision_date,
            # ── Loan data ──
            "loan_type":           fields.get("loan_type"),
            "loan_purpose":        fields.get("loan_purpose"),
            "loan_amount":         _num(fields.get("loan_amount")),
            "interest_rate":       _num(fields.get("interest_rate")),
            "loan_term_months":    fields.get("loan_term_months"),
            "property_type":       fields.get("property_type"),
            "occupancy_type":      fields.get("occupancy_type"),
            "state_code":          fields.get("state_code"),
            "county_code":         fields.get("county_code"),
            "census_tract":        fields.get("census_tract"),
            "lien_status":         fields.get("lien_status") or 1,  # default first lien
            # ── Applicant data — COLLECTED, NEVER used in the decision ──
            "applicant_income":    applicant_income,
            "applicant_ethnicity": _ethnicity_code(fields.get("ethnicity")),
            "applicant_race":      _race_code(fields.get("race")),
            "applicant_sex":       _sex_code(fields.get("sex")),
            "applicant_age":       (int(fields["age"]) if _num(fields.get("age")) else None),
            "demographic_data_provided": any(
                fields.get(k) for k in ("ethnicity", "race", "sex")
            ),
            # ── Action / denial / AUS ──
            "denial_reasons":      denial_reasons,
            "aus_result":          fields.get("aus_result"),
            "aus_system":          fields.get("aus_system"),
            "hmda_reportable":     True,
            "citation":            "12 CFR Part 1003 (Regulation C)",
        }


__all__ = ["HMDALARGenerator", "ACTION_TAKEN_MAP"]
