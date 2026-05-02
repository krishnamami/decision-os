from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, make_signal, upstream_payload


# Compact product catalog. Each entry is a (product, dti_max, ltv_max,
# min_band) row; we filter by dti / ltv / credit_band and return the
# matching set. A real catalog would come from the shared product_ops
# datastore; this is enough to drive the boundary clauses.
_BAND_RANK = {
    "deep_subprime": 0,
    "subprime": 1,
    "thin_file": 1,
    "near_prime": 2,
    "prime": 3,
    "super_prime": 4,
}

_PRODUCTS: list[tuple[str, float, float, str]] = [
    ("conforming_30y", 0.43, 0.95, "near_prime"),
    ("conforming_15y", 0.43, 0.90, "near_prime"),
    ("jumbo_30y",      0.43, 0.80, "prime"),
    ("fha_30y",        0.50, 0.965, "subprime"),
    ("va_30y",         0.50, 1.00, "subprime"),
    ("non_qm",         0.50, 0.85, "subprime"),
]


class ProductEligibilityAgent(LendingPersona):
    """product_eligibility — depends_on dti_calculation + ltv_assessment.

    First decision that combines two upstream contexts. Filters the
    product catalog by dti / ltv / credit_band."""

    DEFAULT_AGENT_ID = "product_eligibility_agent_v1"

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="product_eligibility_agent",
            decision_id="product_eligibility",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        dti_payload = upstream_payload(bundle, "dti_calculation")
        ltv_payload = upstream_payload(bundle, "ltv_assessment")
        credit_payload = upstream_payload(bundle, "credit_assessment")

        dti = dti_payload.get("dti_ratio") or dti_payload.get("dti")
        ltv = ltv_payload.get("ltv_ratio") or ltv_payload.get("ltv")
        credit_band = credit_payload.get("credit_band") or "thin_file"
        applicant_band_rank = _BAND_RANK.get(credit_band, 0)

        eligible: list[str] = []
        exceptions_required: list[str] = []
        for product, dti_max, ltv_max, min_band in _PRODUCTS:
            min_rank = _BAND_RANK[min_band]
            band_ok = applicant_band_rank >= min_rank
            dti_ok = dti is not None and dti <= dti_max
            ltv_ok = ltv is not None and ltv <= ltv_max
            if band_ok and dti_ok and ltv_ok:
                eligible.append(product)
            elif band_ok and (
                (dti is not None and dti <= dti_max + 0.05)
                or (ltv is not None and ltv <= ltv_max + 0.02)
            ):
                exceptions_required.append(product)

        signals = [
            make_signal("dti_ratio", dti, source="dti_calculation"),
            make_signal("ltv_ratio", ltv, source="ltv_assessment"),
            make_signal("credit_band", credit_band, source="credit_assessment"),
            make_signal(
                "eligible_products.count",
                len(eligible),
                direction=(
                    SignalDirection.SUPPORTS
                    if eligible
                    else SignalDirection.CONTRADICTS
                ),
                weight=2.0,
            ),
            make_signal(
                "exceptions_required",
                exceptions_required,
                direction=(
                    SignalDirection.NEUTRAL
                    if not exceptions_required
                    else SignalDirection.CONTRADICTS
                ),
            ),
        ]

        if eligible and not exceptions_required:
            outcome = DecisionOutcome.ALLOW
        elif eligible:
            outcome = DecisionOutcome.RECOMMEND
        elif exceptions_required:
            outcome = DecisionOutcome.ESCALATE
        else:
            outcome = DecisionOutcome.BLOCK

        confidence = 0.85 if eligible else 0.6

        return OfflineReasoning(
            output_payload={
                "eligible_products": eligible,
                "guideline_exceptions_required": exceptions_required,
                "no_eligible_products": not eligible,
                "no_guideline_exceptions_required": not exceptions_required,
                "eligible_with_exceptions": bool(exceptions_required),
                "guideline_exception_required": bool(exceptions_required),
            },
            proposed_outcome=outcome,
            confidence=confidence,
            signals=signals,
            contradictions=[],
            hypothesis=(
                "An applicant qualifies for a product when dti, ltv, and "
                "credit_band are all within the product's guidelines."
            ),
            conclusion=(
                f"dti={dti}, ltv={ltv}, credit_band={credit_band!r} → "
                f"eligible={eligible}, exceptions={exceptions_required}"
            ),
            confidence_basis=(
                "Confidence is high when the upstream values are present "
                "and at least one product matches without exceptions."
            ),
            summary=(
                f"{len(eligible)} eligible products"
                f"{(' (' + str(len(exceptions_required)) + ' with exceptions)' if exceptions_required else '')}; "
                f"proposed {outcome.value}."
            ),
        )


__all__ = ["ProductEligibilityAgent"]
