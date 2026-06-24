from __future__ import annotations

from typing import Optional

from core.aus.du_parser import detect_aus_conflict
from core.aus.reconciliation import AUSReconciliationEngine
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


def _aus_conservatism(aus_result: Optional[dict]) -> int:
    """Rank a parsed AUS result by how PERMISSIVE it is (higher = more
    permissive): approve=2, eligible-but-not-approve (DU Refer/Eligible or LP
    Caution)=1, ineligible=0. Used to pick the more CONSERVATIVE of DU + LP."""
    if not aus_result:
        return 99  # absent -> never "more conservative" than a present result
    if aus_result.get("approve"):
        return 2
    if aus_result.get("eligible"):
        return 1
    return 0


def _more_conservative(du_result: Optional[dict],
                       lp_result: Optional[dict]) -> Optional[dict]:
    """Return the more conservative (less permissive) of the DU and LP results so
    a single Caution/Refer is never masked by the other system's Approve. Returns
    the lone result if only one ran, or None if neither did. Ties favour DU."""
    if du_result and lp_result:
        return lp_result if (_aus_conservatism(lp_result)
                             < _aus_conservatism(du_result)) else du_result
    return du_result or lp_result


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

        # ── RA-AUS-A/C: DU + LP vs Accord reconciliation (advisory, NEUTRAL) ─
        # If a DU and/or LP response was ingested for this app, surface a conflict
        # between the AUS recommendation and Accord's underwriting outcome for
        # human reconciliation. Neither response -> no signal (not all lenders run
        # DU and/or LP). proposed_outcome is never changed here.
        aus_result = ev.get("aus_result")        # DU (RA-AUS-A)
        lp_result = ev.get("aus_result_lp")      # LP (RA-AUS-C)
        # RA-AUS-A signal stays DU-anchored (unchanged behaviour).
        aus_conflict = detect_aus_conflict(aus_result, outcome_label)
        if aus_conflict:
            signals.append(make_signal(
                "AUS_ACCORD_CONFLICT", aus_conflict["du_recommendation"],
                direction=SignalDirection.CONTRADICTS, source="aus", weight=2.0,
                notes=aus_conflict["message"],
            ))

        # ── RA-AUS-B/C: full reconciliation (advisory, OUTCOME-NEUTRAL) ─────
        # Classify the disagreement into one of 4 named cases (risk tier + UW
        # action) for the workbench — repurchase defense. When both DU and LP ran,
        # reconcile against the MORE CONSERVATIVE result (RA-AUS-C) so an LP Caution
        # is never masked by a DU Approve. accord_outcome is the raw UNDERWRITING
        # outcome (block/recommend/escalate/allow), NOT this persona's routing
        # outcome (a decline routes as ALLOW, which would misclassify).
        # proposed_outcome is never changed → 16/16 holds.
        primary_aus = _more_conservative(aus_result, lp_result)
        aus_system = (primary_aus or {}).get("system")
        uw_outcome = (
            (bundle.upstream_outputs.get("underwriting_decision") or {}).get("outcome")
            or outcome_label
        )
        aus_reconciliation = AUSReconciliationEngine().reconcile(uw_outcome, primary_aus)
        if aus_reconciliation.get("reconciliation_required"):
            if aus_reconciliation["risk"] == "HIGH":
                signals.append(make_signal(
                    "AUS_CONFLICT_HIGH_RISK", aus_reconciliation["conflict"],
                    direction=SignalDirection.CONTRADICTS, source="aus", weight=2.0,
                    notes=aus_reconciliation["uw_action"],
                ))
            else:
                signals.append(make_signal(
                    "AUS_CONFLICT_REVIEW", aus_reconciliation["conflict"],
                    direction=SignalDirection.CONTRADICTS, source="aus",
                    notes=aus_reconciliation["uw_action"],
                ))
        elif primary_aus:
            signals.append(make_signal(
                "AUS_ACCORD_AGREEMENT", "HIGH",
                direction=SignalDirection.SUPPORTS, source="aus",
                notes=aus_reconciliation.get("message"),
            ))

        return OfflineReasoning(
            output_payload={
                "routing_target": target,
                # RA-AUS-A — DU result + conflict (None unless DU ran).
                "aus_result": aus_result,
                # RA-AUS-C — LP result (None unless LP ran).
                "aus_result_lp": lp_result,
                "aus_accord_conflict": aus_conflict,
                # RA-AUS-B/C — full reconciliation + confidence (advisory). Run
                # against the more conservative of DU + LP; aus_system names it.
                "aus_reconciliation": aus_reconciliation,
                "aus_confidence": aus_reconciliation.get("confidence"),
                "aus_reconciled_system": aus_system,
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
