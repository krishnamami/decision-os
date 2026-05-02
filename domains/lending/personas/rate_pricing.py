from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, first_object, make_signal, upstream_payload


# Light-touch rate sheet. Real implementations integrate Optimal Blue /
# ICE; this is enough to evaluate the boundary clauses.
_BASE_RATE = 0.0625


class PricingAgent(LendingPersona):
    """rate_pricing — depends_on credit + dti + ltv.

    Computes a base rate plus LLPAs from credit_score, dti, ltv, and
    loan_type. Boundary clauses care about rate_within_normal_band,
    no_manual_adjustments_required, and rate_exceeds_usury_limit."""

    DEFAULT_AGENT_ID = "pricing_agent_v1"

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="pricing_agent",
            decision_id="rate_pricing",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        credit_payload = upstream_payload(bundle, "credit_assessment")
        dti_payload = upstream_payload(bundle, "dti_calculation")
        ltv_payload = upstream_payload(bundle, "ltv_assessment")

        score = credit_payload.get("credit_score") or 700
        dti = dti_payload.get("dti_ratio") or dti_payload.get("dti") or 0.36
        ltv = ltv_payload.get("ltv_ratio") or ltv_payload.get("ltv") or 0.80
        loan = first_object(bundle, "Loan") or {}
        loan_type = loan.get("loan_type") or "conforming"

        # LLPA add-ons: higher LTV / lower score / higher DTI bumps rate.
        llpa = 0.0
        if score < 700:
            llpa += (700 - score) * 0.0005
        if ltv > 0.80:
            llpa += (ltv - 0.80) * 0.05
        if dti > 0.36:
            llpa += (dti - 0.36) * 0.02
        if loan_type == "non_qm":
            llpa += 0.0125

        rate = _BASE_RATE + llpa
        usury_limit = 0.18  # generous federal-level cap
        rate_within_normal_band = rate <= 0.10
        manual_adjustments_required = llpa > 0.02
        pricing_exception_possible = manual_adjustments_required and rate <= 0.10
        usury_violation = rate > usury_limit
        concurrent_lock_conflict = bool(loan.get("concurrent_rate_lock_conflict") or False)

        signals = [
            make_signal("base_rate", _BASE_RATE),
            make_signal(
                "llpa",
                round(llpa, 4),
                direction=(
                    SignalDirection.CONTRADICTS
                    if llpa > 0.02
                    else SignalDirection.NEUTRAL
                ),
            ),
            make_signal(
                "interest_rate",
                round(rate, 4),
                direction=(
                    SignalDirection.SUPPORTS
                    if rate_within_normal_band
                    else SignalDirection.CONTRADICTS
                ),
                weight=2.0,
            ),
            make_signal("loan_type", loan_type),
            make_signal("dti", dti, source="dti_calculation"),
            make_signal("ltv", ltv, source="ltv_assessment"),
            make_signal("credit_score", score, source="credit_assessment"),
        ]
        if concurrent_lock_conflict:
            signals.append(
                make_signal(
                    "concurrent_rate_lock_conflict",
                    True,
                    direction=SignalDirection.CONTRADICTS,
                )
            )

        if usury_violation:
            outcome = DecisionOutcome.BLOCK
            confidence = 0.95
        elif concurrent_lock_conflict:
            outcome = DecisionOutcome.ESCALATE
            confidence = 0.7
        elif rate_within_normal_band and not manual_adjustments_required:
            outcome = DecisionOutcome.ALLOW
            confidence = 0.9
        elif pricing_exception_possible:
            outcome = DecisionOutcome.RECOMMEND
            confidence = 0.75
        else:
            outcome = DecisionOutcome.ESCALATE
            confidence = 0.6

        return OfflineReasoning(
            output_payload={
                "interest_rate": round(rate, 4),
                "llpa": round(llpa, 4),
                "rate_within_normal_band": rate_within_normal_band,
                "no_manual_adjustments_required": not manual_adjustments_required,
                "pricing_exception_possible": pricing_exception_possible,
                "rate_exceeds_usury_limit": usury_violation,
                "concurrent_rate_lock_conflict": concurrent_lock_conflict,
                "loan_type": loan_type,
            },
            proposed_outcome=outcome,
            confidence=confidence,
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Rate is acceptable when base + LLPA stays in the normal "
                "band and no manual adjustments are needed; blocked if it "
                "would exceed the usury cap."
            ),
            conclusion=(
                f"rate={rate:.4f}, llpa={llpa:.4f}, loan_type={loan_type!r} "
                f"→ {outcome.value}"
            ),
            confidence_basis=(
                "Pricing math is deterministic; confidence reflects the "
                "stability of the upstream signals (credit score, dti, ltv)."
            ),
            summary=(
                f"Priced rate {rate:.3%} (LLPA {llpa:.3%}) on {loan_type!r} → "
                f"{outcome.value}."
            ),
        )


__all__ = ["PricingAgent"]
