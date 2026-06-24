"""Freddie Mac Loan Product Advisor (LP / LPA, formerly Loan Prospector) response
parser (RA-AUS-C).

LP is Freddie's automated underwriting system — the Freddie analogue of Fannie's
DU. Lenders approved by both agencies run BOTH and must reconcile two
recommendations whose language and risk scales differ:

  DU                          LP
  Approve/Eligible            Accept              (meets guidelines)
  Refer/Eligible              Caution             (elevated risk, still eligible)
  Refer/Ineligible            Ineligible          (does not meet guidelines)
  Out of Scope/Ineligible     Out of Scope        (LP cannot evaluate this loan)

LP risk classes run A+/A/B/C/D/E (DU uses A–D). The maps below translate both into
the same stable shape the DU parser produces, so AUSReconciliationEngine and
approval_routing consume DU and LP identically.

Pure + DB-less. Recommendation/risk strings come from LP_*_MAP (never inlined), so
consumers are decoupled from LP's exact wording.

KEY SEMANTIC NOTE: ``accept`` is LP-native (only ``Accept`` is a clean go). The
parsed dict ALSO exposes ``approve`` as an alias for ``accept`` so the shared
AUSReconciliationEngine — which reads ``approve``/``eligible`` — handles an LP
result without any engine change. ``Caution`` is ELIGIBLE (eligible=True) but NOT
approve — it is the LP equivalent of DU Refer/Eligible, never of Refer/Ineligible.
"""
from __future__ import annotations

LP_RECOMMENDATION_MAP = {
    "Accept":           "ACCEPT",
    "Accept/Eligible":  "ACCEPT",
    "Caution":          "CAUTION",
    "Caution/Eligible": "CAUTION",
    "Ineligible":       "INELIGIBLE",
    "Out of Scope":     "OUT_OF_SCOPE",
    # LP risk-grade shorthand (some feeds report only the grade).
    "A+":  "ACCEPT",
    "A":   "ACCEPT",
    "B":   "CAUTION",
    "C":   "CAUTION",
    "D":   "INELIGIBLE",
    "E":   "INELIGIBLE",
}

LP_RISK_CLASS_MAP = {
    "A+": "exceptional",
    "A":  "acceptable",
    "B":  "elevated",
    "C":  "high_risk",
    "D":  "very_high_risk",
    "E":  "not_eligible",
}

_ACCEPT = ("ACCEPT",)
_ELIGIBLE = ("ACCEPT", "CAUTION")


class LPParser:
    def parse(self, lp_response: dict) -> dict:
        lp_response = lp_response or {}
        raw_rec = lp_response.get("recommendation", "")
        recommendation = LP_RECOMMENDATION_MAP.get(raw_rec, raw_rec)

        accept = recommendation in _ACCEPT
        eligible = recommendation in _ELIGIBLE

        risk_raw = lp_response.get("risk_class", "")
        risk_class = LP_RISK_CLASS_MAP.get(risk_raw, risk_raw)

        feedbacks = self._parse_feedbacks(lp_response.get("feedbacks", []))
        conditions = self._parse_conditions(lp_response.get("conditions", []))

        return {
            "system":             "LP",
            "version":            lp_response.get("version", ""),
            "key_number":         lp_response.get("key_number", ""),
            "recommendation":     recommendation,
            "raw_recommendation": raw_rec,
            "accept":             accept,
            # ``approve`` aliases ``accept`` so AUSReconciliationEngine (which reads
            # ``approve``) treats an LP result identically to a DU result.
            "approve":            accept,
            "eligible":           eligible,
            "risk_class":         risk_class,
            "feedbacks":          feedbacks,
            "conditions":         conditions,
            "feedback_count":     len(feedbacks),
            "condition_count":    len(conditions),
            "submission_date":    lp_response.get("submission_date", ""),
            "seller_number":      lp_response.get("seller_number", ""),
            "citation":           "Freddie Mac LP Version 5501+",
        }

    @staticmethod
    def _parse_feedbacks(raw: list) -> list:
        parsed = []
        for f in raw or []:
            if isinstance(f, dict):
                parsed.append({
                    "feedback_id":   f.get("id", ""),
                    "feedback_type": f.get("type", ""),
                    "description":   f.get("description", ""),
                    "severity":      f.get("severity", "informational"),
                    "category":      f.get("category", ""),
                })
            elif isinstance(f, str):
                parsed.append({
                    "feedback_id": "", "feedback_type": "message",
                    "description": f, "severity": "informational", "category": "",
                })
        return parsed

    @staticmethod
    def _parse_conditions(raw: list) -> list:
        parsed = []
        for c in raw or []:
            if isinstance(c, dict):
                parsed.append({
                    "condition_id":   c.get("id", ""),
                    "condition_type": c.get("type", "prior_to_purchase"),
                    "description":    c.get("description", ""),
                    "category":       c.get("category", ""),
                })
            elif isinstance(c, str):
                parsed.append({
                    "condition_id": "", "condition_type": "prior_to_purchase",
                    "description": c, "category": "",
                })
        return parsed


__all__ = ["LPParser", "LP_RECOMMENDATION_MAP", "LP_RISK_CLASS_MAP"]
