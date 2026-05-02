from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, first_object, make_signal, upstream_payload


_TARGETS: dict[str, str] = {
    "approve": "approval_letter",
    "conditional_approve": "counter_offer",
    "decline": "decline_notice",
}


class WorkflowRoutingAgent(LendingPersona):
    """approval_routing — depends_on underwriting_decision.

    Routes to the right downstream workflow based on the underwriting
    outcome."""

    DEFAULT_AGENT_ID = "workflow_routing_agent_v1"

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="workflow_routing_agent",
            decision_id="approval_routing",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        underwriting = upstream_payload(bundle, "underwriting_decision")
        outcome_label = underwriting.get("underwriting_outcome") or "conditional_approve"
        applicant = first_object(bundle, "Applicant") or {}
        applicant_dispute = bool(applicant.get("applicant_dispute_flag") or False)

        target = _TARGETS.get(outcome_label, "counter_offer")
        channel = applicant.get("preferred_channel") or applicant.get("channel") or "email"

        signals = [
            make_signal(
                "underwriting_decision.outcome",
                outcome_label,
                source="underwriting_decision",
                direction=SignalDirection.SUPPORTS,
            ),
            make_signal("routing_target", target),
            make_signal("communication_channel", channel),
        ]
        if applicant_dispute:
            signals.append(
                make_signal(
                    "applicant_dispute_flag",
                    True,
                    direction=SignalDirection.CONTRADICTS,
                    weight=2.0,
                )
            )

        if applicant_dispute:
            outcome = DecisionOutcome.ESCALATE
        elif outcome_label in ("approve", "decline"):
            outcome = DecisionOutcome.ALLOW
        elif outcome_label == "conditional_approve":
            outcome = DecisionOutcome.RECOMMEND
        else:
            outcome = DecisionOutcome.ESCALATE

        timeline = "same_day" if outcome_label == "approve" else "next_business_day"

        return OfflineReasoning(
            output_payload={
                "routing_target": target,
                "communication_channel": channel,
                "timeline": timeline,
                "underwriting_decision": {"outcome": outcome_label},
                "applicant_dispute_flag": applicant_dispute,
            },
            proposed_outcome=outcome,
            confidence=0.85 if not applicant_dispute else 0.6,
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Auto-routing is appropriate for clean approvals or "
                "declines; conditional approvals need human acknowledgement; "
                "any open dispute escalates."
            ),
            conclusion=(
                f"underwriting_outcome={outcome_label!r} → target={target!r}, "
                f"channel={channel!r}"
            ),
            confidence_basis=(
                "Deterministic mapping from underwriting outcome to "
                "downstream workflow."
            ),
            summary=(
                f"Routing to {target!r} via {channel!r} ({timeline}); "
                f"proposed {outcome.value}."
            ),
        )


__all__ = ["WorkflowRoutingAgent"]
