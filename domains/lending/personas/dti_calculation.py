from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, first_object, latest_object, make_signal, upstream_payload


class DTICalculationAgent(LendingPersona):
    """dti_calculation — depends_on income_verification.

    Uses verified_income (never stated_income) divided by total monthly
    debt obligations to compute dti. Reads existing_debt_obligations and
    proposed_payment from the Application (own_data) and the IncomeProfile."""

    DEFAULT_AGENT_ID = "underwriting_agent_dti_v1"

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="underwriting_agent",
            decision_id="dti_calculation",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        income_payload = upstream_payload(bundle, "income_verification")
        verified_income_annual = float(
            income_payload.get("verified_income")
            or (latest_object(bundle, "IncomeProfile") or {}).get("verified_income")
            or 0.0
        )
        income_confidence = float(
            income_payload.get("income_confidence_score")
            or (latest_object(bundle, "IncomeProfile") or {}).get(
                "income_confidence_score"
            )
            or 0.0
        )

        application = first_object(bundle, "Application") or {}
        existing_debt_monthly = float(
            application.get("existing_debt_obligations") or 0.0
        )
        proposed_payment = float(application.get("proposed_payment") or 0.0)
        loan = first_object(bundle, "Loan") or {}
        if proposed_payment == 0.0:
            principal = float(loan.get("principal_amount") or 0.0)
            term = max(1, int(loan.get("term_months") or 360))
            rate = float(loan.get("interest_rate") or 0.065)
            proposed_payment = _amortized_payment(principal, rate, term)

        monthly_income = verified_income_annual / 12.0 if verified_income_annual else 0.0
        total_obligations = existing_debt_monthly + proposed_payment
        dti = (
            total_obligations / monthly_income
            if monthly_income > 0
            else float("inf")
        )

        signals = [
            make_signal(
                "verified_income",
                verified_income_annual,
                direction=SignalDirection.SUPPORTS,
                source="income_verification",
            ),
            make_signal(
                "income_verification.confidence",
                income_confidence,
                source="upstream",
            ),
            make_signal("existing_debt_obligations_monthly", existing_debt_monthly),
            make_signal("proposed_payment", proposed_payment),
            make_signal(
                "dti",
                round(dti, 3) if dti != float("inf") else None,
                direction=(
                    SignalDirection.CONTRADICTS
                    if dti > 0.43
                    else SignalDirection.SUPPORTS
                ),
                weight=2.0,
            ),
        ]

        # Per decisions.yaml boundary clauses for dti_calculation.
        if dti == float("inf"):
            outcome = DecisionOutcome.ESCALATE
        elif dti > 0.50:
            outcome = DecisionOutcome.BLOCK
        elif dti <= 0.36:
            outcome = DecisionOutcome.ALLOW
        elif dti <= 0.43:
            outcome = DecisionOutcome.RECOMMEND
        else:
            outcome = DecisionOutcome.ESCALATE

        if income_confidence < 0.85:
            outcome = DecisionOutcome.ESCALATE

        confidence = max(0.4, min(0.95, income_confidence))

        return OfflineReasoning(
            output_payload={
                "dti_ratio": round(dti, 3) if dti != float("inf") else None,
                "dti": round(dti, 3) if dti != float("inf") else None,
                "verified_income": verified_income_annual,
                "monthly_obligations": round(total_obligations, 2),
                "monthly_income": round(monthly_income, 2),
            },
            proposed_outcome=outcome,
            confidence=round(confidence, 3),
            signals=signals,
            contradictions=[],
            hypothesis=(
                "DTI is acceptable when total monthly obligations divided "
                "by verified monthly income is at or below 0.36; conditional "
                "between 0.36 and 0.43; blocked above 0.50."
            ),
            conclusion=(
                f"dti={dti:.3f}, income_confidence={income_confidence:.2f} → "
                f"{outcome.value}"
            ),
            confidence_basis=(
                "Confidence is gated by upstream income_confidence_score — "
                "if income is shaky, the DTI cannot be trusted regardless "
                "of arithmetic."
            ),
            summary=(
                f"DTI {dti:.2%} on verified annual income "
                f"${verified_income_annual:,.0f}; proposed {outcome.value}."
            ),
        )


def _amortized_payment(principal: float, annual_rate: float, term_months: int) -> float:
    if principal <= 0:
        return 0.0
    r = annual_rate / 12.0
    if r == 0:
        return principal / term_months
    return principal * r / (1 - (1 + r) ** -term_months)


__all__ = ["DTICalculationAgent"]
