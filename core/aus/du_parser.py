"""Fannie Mae Desktop Underwriter (DU) response parser (RA-AUS-A).

DU returns one of three top-line recommendations — Approve/Eligible,
Refer/Eligible, Refer/Ineligible — plus findings and conditions. In production
the response arrives as MISMO XML; here we parse a structured dict (the MISMO
adapter is a later slice). The parser extracts the semantic content regardless
of input format so downstream consumers see one stable shape.

Pure + DB-less. The recommendation/risk strings come from DU_*_MAP (never
hardcoded inline), so the persona/enricher reading the result is decoupled from
DU's exact wording.

``detect_aus_conflict`` flags an AUS-vs-Accord disagreement for human
reconciliation (RA-AUS-B). RA-AUS-A only SURFACES the conflict — it never
changes a decision.
"""
from __future__ import annotations

from typing import Optional

DU_RECOMMENDATION_MAP = {
    "Approve/Eligible":        "APPROVE_ELIGIBLE",
    "Approve/Ineligible":      "APPROVE_INELIGIBLE",
    "Refer/Eligible":          "REFER_ELIGIBLE",
    "Refer/Ineligible":        "REFER_INELIGIBLE",
    "Refer with Caution":      "REFER_INELIGIBLE",
    "Out of Scope/Ineligible": "OUT_OF_SCOPE",
    "EA-I":                    "APPROVE_ELIGIBLE",   # DU expanded-approval tiers
    "EA-II":                   "APPROVE_ELIGIBLE",
    "EA-III":                  "APPROVE_ELIGIBLE",
    "MH Advantage":            "APPROVE_ELIGIBLE",
}

DU_RISK_CLASS_MAP = {
    "A": "low_risk",
    "B": "medium_risk",
    "C": "high_risk",
    "D": "not_eligible",
}

_APPROVE = ("APPROVE_ELIGIBLE", "APPROVE_INELIGIBLE")
_ELIGIBLE = ("APPROVE_ELIGIBLE", "REFER_ELIGIBLE")


class DUParser:
    def parse(self, du_response: dict) -> dict:
        du_response = du_response or {}
        raw_rec = du_response.get("recommendation", "")
        recommendation = DU_RECOMMENDATION_MAP.get(raw_rec, raw_rec)

        approve = recommendation in _APPROVE
        eligible = recommendation in _ELIGIBLE

        risk_raw = du_response.get("risk_class", "")
        risk_class = DU_RISK_CLASS_MAP.get(risk_raw, risk_raw)

        findings = self._parse_findings(du_response.get("findings", []))
        conditions = self._parse_conditions(du_response.get("conditions", []))

        return {
            "system":             "DU",
            "version":            du_response.get("version", ""),
            "case_id":            du_response.get("case_id", ""),
            "recommendation":     recommendation,
            "raw_recommendation": raw_rec,
            "approve":            approve,
            "eligible":           eligible,
            "risk_class":         risk_class,
            "findings":           findings,
            "conditions":         conditions,
            "du_condition_count": len(conditions),
            "finding_count":      len(findings),
            "casefile_id":        du_response.get("casefile_id", ""),
            "submission_date":    du_response.get("submission_date", ""),
            "citation":           "Fannie Mae DU Version 11.x",
        }

    @staticmethod
    def _parse_findings(raw_findings: list) -> list:
        parsed = []
        for f in raw_findings or []:
            if isinstance(f, dict):
                parsed.append({
                    "finding_id":   f.get("id", ""),
                    "finding_type": f.get("type", ""),
                    "description":  f.get("description", ""),
                    "severity":     f.get("severity", "informational"),
                    "category":     f.get("category", ""),
                })
            elif isinstance(f, str):
                parsed.append({
                    "finding_id": "", "finding_type": "message",
                    "description": f, "severity": "informational", "category": "",
                })
        return parsed

    @staticmethod
    def _parse_conditions(raw_conditions: list) -> list:
        parsed = []
        for c in raw_conditions or []:
            if isinstance(c, dict):
                parsed.append({
                    "condition_id":   c.get("id", ""),
                    "condition_type": c.get("type", "prior_to_purchase"),
                    "description":    c.get("description", ""),
                    "category":       c.get("category", ""),
                    "due":            c.get("due", "prior_to_purchase"),
                })
            elif isinstance(c, str):
                parsed.append({
                    "condition_id": "", "condition_type": "prior_to_purchase",
                    "description": c, "category": "", "due": "prior_to_purchase",
                })
        return parsed


def detect_aus_conflict(
    aus_result: Optional[dict], accord_outcome_label: str
) -> Optional[dict]:
    """Compare a parsed DU result with Accord's underwriting outcome
    (approve / conditional_approve / decline). Returns a conflict descriptor when
    they materially disagree, else None. ADVISORY — never changes a decision;
    RA-AUS-B resolves it. No DU result -> no conflict (not all lenders run DU)."""
    if not aus_result:
        return None

    rec = aus_result.get("recommendation", "")
    du_approve = bool(aus_result.get("approve"))
    du_eligible = bool(aus_result.get("eligible"))
    du_refer = rec.startswith("REFER")

    accord_declined = accord_outcome_label == "decline"
    accord_approved = accord_outcome_label in ("approve", "conditional_approve")

    message = None
    if du_approve and accord_declined:
        message = (f"DU {rec} but Accord declined — reconcile before action "
                   f"(RA-AUS-B).")
    elif (du_refer or not du_eligible) and accord_approved:
        message = (f"DU {rec} but Accord {accord_outcome_label} — verify "
                   f"manually before auto-routing.")
    if message is None:
        return None
    return {
        "conflict": True,
        "message": message,
        "du_recommendation": rec,
        "accord_outcome": accord_outcome_label,
        "severity": "amber",
    }


__all__ = ["DUParser", "detect_aus_conflict",
           "DU_RECOMMENDATION_MAP", "DU_RISK_CLASS_MAP"]
