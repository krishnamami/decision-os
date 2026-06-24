"""AUS reconciliation engine (RA-AUS-B) — Accord vs DU disagreement.

When Accord and DU agree, the loan proceeds with high confidence. When they
disagree, the underwriter must understand WHY before acting — this is the
repurchase-defense surface. RA-AUS-A's ``detect_aus_conflict`` is the lightweight
boolean flag (and the AUS_ACCORD_CONFLICT signal); this engine is the detailed
classifier layered on top, turning a disagreement into one of four named cases
with a risk tier, plain-English explanation, the required UW action, and the
HMDA/fair-lending implication.

Pure + DB-less. ADVISORY ONLY — it never changes a decision (RULE: proposed_outcome
untouched). The ``accord_outcome`` is the UNDERWRITING decision's raw outcome
(block / recommend / escalate / allow), NOT approval_routing's routing outcome —
a decline routes as ALLOW, so using the routing outcome would misclassify.
"""
from __future__ import annotations

from typing import Optional

# Conflict type -> UW-facing explanation. Keys are stable; never inline the
# strings at call sites.
CONFLICT_EXPLANATIONS = {
    "ACCORD_BLOCK_DU_APPROVE": {
        "risk": "HIGH",
        "title": "Accord blocked — DU approved",
        "explanation": (
            "Accord Decision OS identified a blocking condition that DU did not "
            "flag. Common causes: title defects (DU does not review title), "
            "evidence conflicts (DU trusts stated data), overlay rules (Accord "
            "enforces lender overlays DU does not know). Review the Accord block "
            "reasons before proceeding."
        ),
        "uw_action": (
            "Investigate the Accord block reason. If Accord is correct: follow "
            "Accord, document an exception if proceeding. If the block is "
            "erroneous: clear it in Accord with documented rationale. Cannot "
            "override below the agency floor without exception approval."
        ),
        "hmda_implication": "Decision must follow a documented process for fair-lending audit.",
    },
    "ACCORD_RECOMMEND_DU_REFER": {
        "risk": "HIGH",
        "title": "DU referred (ineligible) — Accord recommended",
        "explanation": (
            "DU issued a Refer/Ineligible recommendation: manual underwriting is "
            "required and DU sees the loan as not meeting guidelines. DU may have "
            "identified risk factors not yet captured in Accord. Review DU "
            "findings carefully before relying on the Accord recommendation."
        ),
        "uw_action": (
            "Review all DU findings. Add conditions to address each DU concern. "
            "Manual underwriting required per DU Refer guidance. Document "
            "compensating factors if proceeding."
        ),
        "hmda_implication": "Manual-underwriting pathway — ensure consistent treatment.",
    },
    "ACCORD_ESCALATE_DU_APPROVE": {
        "risk": "MEDIUM",
        "title": "Accord escalated — DU approved",
        "explanation": (
            "Accord requires human review for a specific condition while DU "
            "approved the loan. Resolve the Accord escalation reason before "
            "proceeding to closing."
        ),
        "uw_action": (
            "Review the Accord escalation signals. Obtain documentation to clear "
            "the escalation. Once cleared, the loan may proceed per DU approval."
        ),
        "hmda_implication": "Document the escalation resolution for the audit trail.",
    },
    "ACCORD_RECOMMEND_DU_REFER_ELIGIBLE": {
        "risk": "LOW",
        "title": "DU referred (eligible) — Accord recommended",
        "explanation": (
            "Both systems agree the loan is eligible; DU flagged items for manual "
            "review. The Accord recommendation is consistent with eligibility."
        ),
        "uw_action": (
            "Review DU findings. Address any documentation gaps DU identified. "
            "Proceed with the standard underwriting process."
        ),
        "hmda_implication": "Standard manual-review pathway.",
    },
}


def _classify(accord_outcome: str, du_approve: bool, du_eligible: bool) -> Optional[str]:
    """Map (Accord underwriting outcome, DU result) to a conflict type, or None
    when the two systems agree. ``allow`` (clean approve) is treated like
    ``recommend`` for the DU-refer cases."""
    accord_block = accord_outcome in ("block", "deny")
    accord_recommend = accord_outcome in ("recommend", "approve", "allow")
    accord_escalate = accord_outcome == "escalate"

    if accord_block and du_approve:
        return "ACCORD_BLOCK_DU_APPROVE"
    if accord_recommend and not du_approve and not du_eligible:
        return "ACCORD_RECOMMEND_DU_REFER"
    if accord_escalate and du_approve:
        return "ACCORD_ESCALATE_DU_APPROVE"
    if accord_recommend and not du_approve and du_eligible:
        return "ACCORD_RECOMMEND_DU_REFER_ELIGIBLE"
    return None


class AUSReconciliationEngine:
    def reconcile(self, accord_outcome: str, aus_result: Optional[dict]) -> dict:
        if not aus_result:
            return {
                "reconciliation_required": False,
                "conflict": None,
                "message": "No AUS response available for comparison.",
            }

        du_approve = bool(aus_result.get("approve"))
        du_eligible = bool(aus_result.get("eligible"))
        du_rec = aus_result.get("recommendation", "")

        conflict_type = _classify(accord_outcome, du_approve, du_eligible)

        if not conflict_type:
            return {
                "reconciliation_required": False,
                "conflict": None,
                "accord_outcome": accord_outcome,
                "du_recommendation": du_rec,
                "agreement": True,
                "confidence": "HIGH",
                "message": f"Accord and DU agree: {accord_outcome} / {du_rec}",
            }

        e = CONFLICT_EXPLANATIONS[conflict_type]
        return {
            "reconciliation_required": True,
            "conflict": conflict_type,
            "risk": e["risk"],
            "title": e["title"],
            "explanation": e["explanation"],
            "uw_action": e["uw_action"],
            "hmda_implication": e["hmda_implication"],
            "accord_outcome": accord_outcome,
            "du_recommendation": du_rec,
            "du_approve": du_approve,
            "du_eligible": du_eligible,
            "agreement": False,
            "confidence": "LOW" if e["risk"] == "HIGH" else "MEDIUM",
        }


__all__ = ["AUSReconciliationEngine", "CONFLICT_EXPLANATIONS"]
