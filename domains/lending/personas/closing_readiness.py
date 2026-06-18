from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, first_object, make_signal, upstream_payload


class ClosingAgent(LendingPersona):
    """closing_readiness — depends_on underwriting_decision +
    compliance_check. Validates conditions, title, insurance, and
    CD-timing before scheduling closing."""

    DEFAULT_AGENT_ID = "closing_agent_v1"

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="closing_agent",
            decision_id="closing_readiness",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        compliance_record = first_object(bundle, "ComplianceRecord") or {}
        compliance_payload = upstream_payload(bundle, "compliance_check")
        underwriting_payload = upstream_payload(bundle, "underwriting_decision")
        prop = first_object(bundle, "Property") or {}

        title_status = (prop.get("title_status") or "clear").lower()
        title_clear = title_status == "clear"
        title_defect = title_status == "defect"

        # CD-timing violation is an authoritative loan fact (TRID 3-business-day
        # rule), surfaced on the URLA; default False (compliant) when unflagged.
        # Rate-lock days-remaining comes from loan_terms (builder-computed).
        loan = first_object(bundle, "Loan") or {}
        urla = loan.get("urla") or {}
        cd_timing_violation = bool(urla.get("cd_timing_violation"))
        cd_timing_compliant = not cd_timing_violation
        days_until_rate_lock_expiry = loan.get("days_until_rate_lock_expiry")
        try:
            rate_lock_expiring_soon = (
                days_until_rate_lock_expiry is not None
                and int(days_until_rate_lock_expiry) <= 5
            )
        except (TypeError, ValueError):
            rate_lock_expiring_soon = False
        compliance_outcome = compliance_payload.get("outcome") or compliance_payload.get("decision")

        # Own-data: final conditions checklist + insurance binder.
        conditions = compliance_record.get("final_conditions_checklist") or {}
        all_conditions_cleared = bool(conditions.get("all_cleared", True))
        minor_conditions_outstanding = bool(
            conditions.get("minor_outstanding") or False
        )
        insurance_binder = bool(compliance_record.get("insurance_binder", True))
        insurance_gap = not insurance_binder
        lien_dispute = bool(prop.get("lien_status") and prop.get("lien_status") != "clear")

        underwriting_outcome = (
            underwriting_payload.get("underwriting_outcome") or "conditional_approve"
        )

        signals = [
            make_signal(
                "all_conditions_cleared",
                all_conditions_cleared,
                direction=(
                    SignalDirection.SUPPORTS
                    if all_conditions_cleared
                    else SignalDirection.CONTRADICTS
                ),
            ),
            make_signal(
                "cd_timing_compliant",
                cd_timing_compliant,
                direction=(
                    SignalDirection.SUPPORTS
                    if cd_timing_compliant
                    else SignalDirection.CONTRADICTS
                ),
                weight=2.0,
            ),
            make_signal("title_clear", title_clear),
            make_signal("title_defect", title_defect),
            make_signal("compliance_check.decision", compliance_outcome),
            make_signal("underwriting_outcome", underwriting_outcome),
            make_signal("insurance_gap", insurance_gap),
            make_signal("lien_dispute", lien_dispute),
        ]

        if title_defect or compliance_outcome == "block" or cd_timing_violation:
            outcome = DecisionOutcome.BLOCK
            confidence = 0.95
        elif rate_lock_expiring_soon:
            # Rate lock expiring within 5 days — needs UW action, not a block.
            outcome = DecisionOutcome.ESCALATE
            confidence = 0.7
        elif lien_dispute or insurance_gap:
            outcome = DecisionOutcome.ESCALATE
            confidence = 0.65
        elif (
            all_conditions_cleared
            and cd_timing_compliant
            and title_clear
            and underwriting_outcome == "approve"
        ):
            outcome = DecisionOutcome.ALLOW
            confidence = 0.9
        elif minor_conditions_outstanding:
            outcome = DecisionOutcome.RECOMMEND
            confidence = 0.75
        else:
            outcome = DecisionOutcome.ESCALATE
            confidence = 0.6

        return OfflineReasoning(
            output_payload={
                "clear_to_close": outcome == DecisionOutcome.ALLOW,
                "outstanding_conditions": [] if all_conditions_cleared else ["minor_review"],
                "all_conditions_cleared": all_conditions_cleared,
                "cd_timing_compliant": cd_timing_compliant,
                "cd_timing_violation": cd_timing_violation,
                "days_until_rate_lock_expiry": days_until_rate_lock_expiry,
                "rate_lock_expiring_soon": rate_lock_expiring_soon,
                "title_clear": title_clear,
                "title_defect": title_defect,
                "minor_conditions_outstanding": minor_conditions_outstanding,
                "insurance_gap": insurance_gap,
                "lien_dispute": lien_dispute,
                "underwriting_outcome": underwriting_outcome,
                "compliance_check": {"outcome": compliance_outcome},
            },
            proposed_outcome=outcome,
            confidence=confidence,
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Loan is clear-to-close when all conditions are satisfied, "
                "title is clean, CD-timing is compliant, and underwriting "
                "approved cleanly."
            ),
            conclusion=(
                f"all_conditions={all_conditions_cleared}, title_clear="
                f"{title_clear}, cd_timing_compliant={cd_timing_compliant}, "
                f"underwriting={underwriting_outcome!r} → {outcome.value}"
            ),
            confidence_basis=(
                "High confidence on hard fails (title defect, compliance "
                "block, CD-timing violation); softer confidence on the "
                "minor-conditions branch where reviewer judgement matters."
            ),
            summary=(
                f"Closing posture: {outcome.value} "
                f"(title_clear={title_clear}, "
                f"cd_timing_compliant={cd_timing_compliant})."
            ),
        )


__all__ = ["ClosingAgent"]
