from __future__ import annotations

from typing import Optional

from core.aus.du_parser import detect_aus_conflict
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

        # ── RA-PERSONA-C: evidence quality (advisory, OUTCOME-NEUTRAL) ────
        # Surfaces a routing PREFERENCE (conflicts/weak evidence lean toward
        # manual review) as signals + provenance, but does NOT change the
        # routing outcome above — 16/16 holds. A future iteration may consume
        # these to bias auto-approve vs manual; that is a deliberate outcome
        # change out of scope here. Threshold is the catalogue documentation-
        # confidence floor (Fannie B3-3.1-01, governed_by=agency).
        ev = first_object(bundle, "evidence") or {}
        evidence_populated = bool(ev.get("evidence_populated"))
        evidence_any_conflicts = bool(ev.get("evidence_any_conflicts"))
        evidence_overall_conf = ev.get("evidence_overall_confidence")
        conf_min = ev.get("income_confidence_min")
        if conf_min is None:
            conf_min = 0.75
        evidence_threshold_trace = ev.get("income_confidence_threshold_trace")
        if evidence_populated and evidence_any_conflicts:
            signals.append(make_signal(
                "ROUTE_CONFLICT_PRESENT", True,
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=("Evidence conflict on file — prefer manual review over "
                       "auto-approve routing."),
            ))
        if (evidence_populated and evidence_overall_conf is not None
                and evidence_overall_conf < conf_min):
            signals.append(make_signal(
                "ROUTE_LOW_CONFIDENCE", round(float(evidence_overall_conf), 3),
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=(f"Overall evidence confidence {evidence_overall_conf:.0%} "
                       f"below {conf_min:.0%} (Fannie B3-3.1-01)."),
            ))

        # ── RA-AUS-A: DU vs Accord reconciliation (advisory, OUTCOME-NEUTRAL) ─
        # If a DU response was ingested for this app, surface a conflict between
        # DU's recommendation and Accord's underwriting outcome for human
        # reconciliation (RA-AUS-B resolves it). No DU response -> no signal
        # (not all lenders run DU). proposed_outcome is never changed here.
        aus_result = ev.get("aus_result")
        aus_conflict = detect_aus_conflict(aus_result, outcome_label)
        if aus_conflict:
            signals.append(make_signal(
                "AUS_ACCORD_CONFLICT", aus_conflict["du_recommendation"],
                direction=SignalDirection.CONTRADICTS, source="aus", weight=2.0,
                notes=aus_conflict["message"],
            ))

        return OfflineReasoning(
            output_payload={
                "routing_target": target,
                # RA-AUS-A — DU/AUS result + conflict (None unless DU ran).
                "aus_result": aus_result,
                "aus_accord_conflict": aus_conflict,
                # RA-PERSONA-C: evidence provenance (advisory).
                "evidence_populated": evidence_populated,
                "route_evidence_confidence": (
                    round(float(evidence_overall_conf), 3)
                    if evidence_overall_conf is not None else None
                ),
                "route_evidence_conflicts": evidence_any_conflicts,
                "route_evidence_governed_by": (
                    (evidence_threshold_trace or {}).get("governed_by")
                ),
                "evidence_threshold_trace": evidence_threshold_trace,
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
