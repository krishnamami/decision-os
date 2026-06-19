from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, first_object, make_signal, upstream_payload


_MAX_LTV_BY_BAND: dict[str, float] = {
    "super_prime": 0.97,
    "prime": 0.95,
    "near_prime": 0.90,
    "subprime": 0.80,
    "deep_subprime": 0.70,
    "thin_file": 0.80,
}


class LTVAssessmentAgent(LendingPersona):
    """ltv_assessment — depends_on credit_assessment.

    Computes loan_to_value ratio against the Property's appraised value
    and exposes max_allowable_ltv from the upstream credit_band."""

    DEFAULT_AGENT_ID = "underwriting_agent_ltv_v1"

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
            decision_id="ltv_assessment",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        credit_payload = upstream_payload(bundle, "credit_assessment")
        credit_band = credit_payload.get("credit_band") or "thin_file"
        prop = first_object(bundle, "Property") or {}
        loan = first_object(bundle, "Loan") or {}

        appraised = float(prop.get("appraised_value") or 0.0)
        purchase_price = float(prop.get("purchase_price") or appraised)
        down_payment = float(prop.get("down_payment") or 0.0)
        # loan_amount comes from this decision's Property field_map (the bundle
        # has no "Loan" object); fall back to the Loan principal / equity math
        # only when the view didn't supply it. Without prop.loan_amount the
        # fallback used purchase_price-down_payment, which (when the view's
        # purchase_price is null) collapses to appraised -> ltv==1.0 for every
        # loan, wrongly blocking ltv_assessment and cascading downstream.
        loan_amount = float(
            prop.get("loan_amount")
            or loan.get("principal_amount")
            or max(0.0, purchase_price - down_payment)
        )
        appraisal_disputed = bool(prop.get("appraisal_disputed") or False)

        ltv = loan_amount / appraised if appraised > 0 else float("inf")
        max_ltv = _MAX_LTV_BY_BAND.get(credit_band, 0.80)

        signals = [
            make_signal("appraised_value", appraised, source="property"),
            make_signal("purchase_price", purchase_price),
            make_signal("loan_amount", loan_amount),
            make_signal("credit_band", credit_band, source="credit_assessment"),
            make_signal(
                "ltv",
                round(ltv, 3) if ltv != float("inf") else None,
                direction=(
                    SignalDirection.CONTRADICTS
                    if ltv > max_ltv
                    else SignalDirection.SUPPORTS
                ),
                weight=2.0,
            ),
            make_signal("max_allowable_ltv", max_ltv, source="credit_band"),
        ]
        if appraisal_disputed:
            signals.append(
                make_signal(
                    "appraisal_disputed",
                    True,
                    direction=SignalDirection.CONTRADICTS,
                    weight=2.0,
                )
            )

        if appraisal_disputed:
            outcome = DecisionOutcome.ESCALATE
        elif ltv == float("inf"):
            outcome = DecisionOutcome.ESCALATE
        elif ltv > 0.97:
            outcome = DecisionOutcome.BLOCK
        elif ltv <= 0.80:
            outcome = DecisionOutcome.ALLOW
        elif ltv <= 0.95:
            outcome = DecisionOutcome.RECOMMEND
        else:
            outcome = DecisionOutcome.ESCALATE

        confidence = 0.9 if appraised > 0 and not appraisal_disputed else 0.6

        return OfflineReasoning(
            output_payload={
                "ltv_ratio": round(ltv, 3) if ltv != float("inf") else None,
                "ltv": round(ltv, 3) if ltv != float("inf") else None,
                "max_allowable_ltv": max_ltv,
                "appraised_value": appraised,
                "loan_amount": loan_amount,
                "appraisal_disputed": appraisal_disputed,
            },
            proposed_outcome=outcome,
            confidence=confidence,
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Standard LTV is acceptable at <= 0.80; conditional up to "
                "0.95; blocked above 0.97. Credit band caps the maximum "
                "allowable LTV."
            ),
            conclusion=(
                f"ltv={ltv:.3f}, credit_band={credit_band!r}, "
                f"max_allowable={max_ltv:.2f} → {outcome.value}"
            ),
            confidence_basis=(
                "Appraisal is the dominant signal — high confidence when "
                "the appraisal is undisputed; lower when an appraisal "
                "challenge is open."
            ),
            summary=(
                f"LTV {ltv:.2%} for credit_band={credit_band!r} "
                f"(max {max_ltv:.0%}); proposed {outcome.value}."
            ),
        )


__all__ = ["LTVAssessmentAgent"]
