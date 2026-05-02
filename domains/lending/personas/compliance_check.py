from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, first_object, make_signal


class ComplianceAgent(LendingPersona):
    """compliance_check — HMDA, ECOA / fair-lending, state rules,
    TRID. High-risk; blocks closing if it blocks."""

    DEFAULT_AGENT_ID = "compliance_agent_v1"

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="compliance_agent",
            decision_id="compliance_check",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        compliance = first_object(bundle, "ComplianceRecord") or {}
        hmda_complete = bool(compliance.get("all_hmda_fields_complete") or False)
        fair_lending_violation = bool(compliance.get("fair_lending_violation") or False)
        missing_disclosures = bool(compliance.get("missing_required_disclosures") or False)
        state_rules_passed = bool(compliance.get("state_rules_passed") or False)
        cd_timing_compliant = bool(compliance.get("cd_timing_compliant") or False)
        regulatory_ambiguity = bool(compliance.get("regulatory_ambiguity") or False)
        mixed_jurisdiction = bool(compliance.get("mixed_jurisdiction") or False)

        signals = [
            make_signal(
                "all_hmda_fields_complete",
                hmda_complete,
                direction=(
                    SignalDirection.SUPPORTS
                    if hmda_complete
                    else SignalDirection.CONTRADICTS
                ),
            ),
            make_signal("fair_lending_violation", fair_lending_violation),
            make_signal("missing_required_disclosures", missing_disclosures),
            make_signal("state_rules_passed", state_rules_passed),
            make_signal("cd_timing_compliant", cd_timing_compliant),
        ]

        if fair_lending_violation or missing_disclosures:
            outcome = DecisionOutcome.BLOCK
            confidence = 0.95
        elif regulatory_ambiguity or mixed_jurisdiction:
            outcome = DecisionOutcome.ESCALATE
            confidence = 0.6
        elif hmda_complete and state_rules_passed:
            outcome = DecisionOutcome.ALLOW
            confidence = 0.9
        else:
            outcome = DecisionOutcome.RECOMMEND
            confidence = 0.7

        # decisions.yaml uses a `no_fair_lending_flags` boundary token.
        no_fair_lending_flags = not fair_lending_violation
        minor_data_gap = not hmda_complete and not missing_disclosures

        return OfflineReasoning(
            output_payload={
                "compliance_cleared": outcome == DecisionOutcome.ALLOW,
                "all_hmda_fields_complete": hmda_complete,
                "no_fair_lending_flags": no_fair_lending_flags,
                "state_rules_passed": state_rules_passed,
                "minor_data_gap": minor_data_gap,
                "fair_lending_violation": fair_lending_violation,
                "missing_required_disclosures": missing_disclosures,
                "regulatory_ambiguity": regulatory_ambiguity,
                "mixed_jurisdiction": mixed_jurisdiction,
            },
            proposed_outcome=outcome,
            confidence=confidence,
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Application is compliant when all HMDA fields are present, "
                "no fair-lending flags exist, and state rules pass."
            ),
            conclusion=(
                f"hmda_complete={hmda_complete}, fair_lending_violation="
                f"{fair_lending_violation}, missing_disclosures="
                f"{missing_disclosures} → {outcome.value}"
            ),
            confidence_basis=(
                "Hard rules drive blocks deterministically; soft ESCALATE "
                "paths reflect ambiguity in mixed-jurisdiction or unclear "
                "state-rule cases."
            ),
            summary=(
                f"Compliance posture: {outcome.value} "
                f"(hmda_complete={hmda_complete}, "
                f"fair_lending_violation={fair_lending_violation})."
            ),
        )


__all__ = ["ComplianceAgent"]
