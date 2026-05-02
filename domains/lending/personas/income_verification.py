from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, latest_object, make_signal


class IncomeVerificationAgent(LendingPersona):
    """income_verification — produce verified_income + income_confidence.

    Boundary clauses (decisions.yaml) want income_confidence_score,
    employment_type, payroll_verified, income_discrepancy_pct,
    multiple_income_sources, foreign_income."""

    DEFAULT_AGENT_ID = "income_verification_agent_v1"

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="income_verification_agent",
            decision_id="income_verification",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        income = latest_object(bundle, "IncomeProfile") or {}
        stated = float(income.get("stated_income") or 0.0)
        verified = float(income.get("verified_income") or 0.0)
        employment_type = income.get("employment_type") or "other"
        payroll_verified = bool(income.get("payroll_verified") or False)
        multiple_sources = bool(income.get("multiple_income_sources") or False)
        foreign_income = bool(income.get("foreign_income") or False)

        # Discrepancy + confidence
        if stated > 0 and verified > 0:
            discrepancy = abs(stated - verified) / stated
        else:
            discrepancy = 0.0

        existing_confidence = income.get("income_confidence_score")
        if existing_confidence is None:
            base = 0.6
            if payroll_verified:
                base += 0.25
            if employment_type == "salaried":
                base += 0.1
            if employment_type in ("self_employed", "contractor"):
                base -= 0.1
            base -= min(discrepancy, 0.5)
            confidence_score = max(0.0, min(1.0, base))
        else:
            confidence_score = float(existing_confidence)

        signals = [
            make_signal("verified_income", verified, source="payroll"),
            make_signal("stated_income", stated, source="application"),
            make_signal(
                "income_confidence_score",
                round(confidence_score, 3),
                direction=(
                    SignalDirection.SUPPORTS
                    if confidence_score >= 0.9
                    else SignalDirection.NEUTRAL
                ),
            ),
            make_signal("employment_type", employment_type),
            make_signal("payroll_verified", payroll_verified),
        ]
        if discrepancy > 0:
            signals.append(
                make_signal(
                    "income_discrepancy_pct",
                    round(discrepancy, 3),
                    direction=(
                        SignalDirection.CONTRADICTS
                        if discrepancy > 0.25
                        else SignalDirection.NEUTRAL
                    ),
                )
            )

        # Outcome — reflects boundary intent.
        if discrepancy > 0.25:
            outcome = DecisionOutcome.BLOCK
        elif multiple_sources or foreign_income:
            outcome = DecisionOutcome.ESCALATE
        elif confidence_score >= 0.9 and employment_type == "salaried" and payroll_verified:
            outcome = DecisionOutcome.ALLOW
        elif confidence_score >= 0.75:
            outcome = DecisionOutcome.RECOMMEND
        else:
            outcome = DecisionOutcome.ESCALATE

        return OfflineReasoning(
            output_payload={
                "verified_income": verified,
                "income_confidence_score": round(confidence_score, 3),
                "employment_type": employment_type,
                "payroll_verified": payroll_verified,
                "income_discrepancy_pct": round(discrepancy, 3),
                "multiple_income_sources": multiple_sources,
                "foreign_income": foreign_income,
            },
            proposed_outcome=outcome,
            confidence=round(confidence_score, 3),
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Verified income is reliable when payroll is verified, "
                "discrepancy is below 25%, and the employment type is "
                "salaried."
            ),
            conclusion=(
                f"income_confidence_score={confidence_score:.2f}, "
                f"employment_type={employment_type!r}, "
                f"payroll_verified={payroll_verified} → {outcome.value}"
            ),
            confidence_basis=(
                "Confidence reflects the agreement between stated and "
                "verified income, plus the strength of the employment "
                "evidence."
            ),
            summary=(
                f"Verified income ${verified:,.0f} with confidence "
                f"{confidence_score:.2f}; proposed {outcome.value}."
            ),
        )


__all__ = ["IncomeVerificationAgent"]
