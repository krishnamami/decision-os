from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, make_signal, upstream_payload


_UPSTREAM_DECISIONS = (
    "income_verification",
    "credit_assessment",
    "fraud_screening",
    "dti_calculation",
    "ltv_assessment",
    "product_eligibility",
)


class SeniorUnderwritingAgent(LendingPersona):
    """underwriting_decision — synthesise everything upstream.

    Highest-stakes decision in the pipeline. Boundary keys:
      all_upstream_auto_cleared, risk_score, no_exceptions_required,
      any_upstream_hard_block, fraud_screening.decision,
      senior_underwriter_review_required."""

    DEFAULT_AGENT_ID = "senior_underwriting_agent_v1"

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="senior_underwriting_agent",
            decision_id="underwriting_decision",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        per_upstream: dict[str, dict] = {
            d: bundle.upstream_outputs.get(d) or {} for d in _UPSTREAM_DECISIONS
        }
        outcomes = {d: (per_upstream[d].get("outcome") or "missing") for d in _UPSTREAM_DECISIONS}

        any_block = any(o == "block" for o in outcomes.values())
        all_auto_cleared = all(o == "allow" for o in outcomes.values())
        any_escalate_or_recommend = any(
            o in ("escalate", "recommend") for o in outcomes.values()
        )

        # Risk score: 1.0 if any upstream blocked, else weighted
        # combination of upstream non-allow outcomes. Crude but
        # adequate for the boundary.
        if any_block:
            risk_score = 1.0
        else:
            non_allow = sum(1 for o in outcomes.values() if o != "allow")
            risk_score = min(1.0, 0.10 + 0.15 * non_allow)

        senior_review_required = (
            risk_score > 0.60
            or any_escalate_or_recommend
        )

        # Fraud-specific signal expected by boundary `fraud_screening.decision`.
        fraud_outcome = outcomes.get("fraud_screening")

        signals = [
            make_signal(
                "all_upstream_auto_cleared",
                all_auto_cleared,
                direction=(
                    SignalDirection.SUPPORTS
                    if all_auto_cleared
                    else SignalDirection.CONTRADICTS
                ),
                weight=2.0,
            ),
            make_signal(
                "risk_score",
                round(risk_score, 3),
                direction=(
                    SignalDirection.CONTRADICTS
                    if risk_score > 0.60
                    else SignalDirection.NEUTRAL
                ),
                weight=2.0,
            ),
            make_signal("any_upstream_hard_block", any_block),
            make_signal("fraud_screening.decision", fraud_outcome),
            make_signal(
                "senior_underwriter_review_required", senior_review_required
            ),
        ]

        if any_block or fraud_outcome == "block":
            outcome = DecisionOutcome.BLOCK
            confidence = 0.95
        elif all_auto_cleared and risk_score <= 0.25:
            outcome = DecisionOutcome.ALLOW
            confidence = 0.85
        elif risk_score <= 0.60:
            outcome = DecisionOutcome.RECOMMEND
            confidence = 0.7
        else:
            outcome = DecisionOutcome.ESCALATE
            confidence = 0.6

        underwriting_outcome = {
            DecisionOutcome.ALLOW: "approve",
            DecisionOutcome.RECOMMEND: "conditional_approve",
            DecisionOutcome.ESCALATE: "conditional_approve",
            DecisionOutcome.BLOCK: "decline",
        }[outcome]

        return OfflineReasoning(
            output_payload={
                "underwriting_outcome": underwriting_outcome,
                "risk_score": round(risk_score, 3),
                "all_upstream_auto_cleared": all_auto_cleared,
                "any_upstream_hard_block": any_block,
                "no_exceptions_required": all_auto_cleared,
                "senior_underwriter_review_required": senior_review_required,
                "exceptions_required": [
                    d for d, o in outcomes.items() if o not in ("allow", "missing")
                ],
                "upstream_outcomes": outcomes,
            },
            proposed_outcome=outcome,
            confidence=confidence,
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Auto-approval requires every upstream decision to have "
                "cleared cleanly; any block hard-fails; soft signals route "
                "to recommend or escalate based on aggregated risk."
            ),
            conclusion=(
                f"all_clean={all_auto_cleared}, any_block={any_block}, "
                f"risk_score={risk_score:.2f} → {outcome.value} "
                f"({underwriting_outcome})"
            ),
            confidence_basis=(
                "Confidence is highest on a clean sweep or a clear hard "
                "block; lower on soft mixed signals where senior review "
                "is the right answer."
            ),
            summary=(
                f"Underwriting outcome {underwriting_outcome!r} "
                f"(risk_score {risk_score:.2f}) — proposed {outcome.value}."
            ),
        )


__all__ = ["SeniorUnderwritingAgent"]
