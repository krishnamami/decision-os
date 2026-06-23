from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from core.collateral.appraisal_analyzer import AppraisalAnalyzer
from core.collateral.property_eligibility_resolver import (
    PropertyEligibilityResolver,
)

from .base import LendingPersona, OfflineReasoning, first_object, make_signal, upstream_payload


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

        # VA entitlement gate (runs before the generic catalog filter). VA
        # loans need a Certificate of Eligibility check; second-use entitlement
        # escalates, and insufficient remaining entitlement blocks.
        # product_eligibility's bundle is an "Application" object (the
        # vw_product_eligibility_context field_map), not a "Loan" — read the
        # VA fields from there. The view exposes loan_type from the URLA and
        # the va_entitlement_* columns.
        _app = first_object(bundle, "Application") or {}
        if str(_app.get("loan_type") or "").upper() == "VA":
            def _num(x):
                try:
                    return float(x)
                except (TypeError, ValueError):
                    return None
            va_used = _app.get("va_entitlement_used")
            va_remaining = _app.get("va_entitlement_remaining")
            loan_amt = _num(_app.get("loan_amount")) or 0.0
            rem = _num(va_remaining)
            insufficient = rem is not None and rem < loan_amt * 0.25
            va_outcome = DecisionOutcome.BLOCK if insufficient else DecisionOutcome.ESCALATE
            return OfflineReasoning(
                output_payload={
                    "loan_type": "VA",
                    "va_entitlement_used": va_used,
                    "va_entitlement_remaining": va_remaining,
                    "eligible_products": [] if insufficient else ["va_30y"],
                    # block_if reads no_eligible_products; escalate_if reads
                    # guideline_exception_required (COE / second-use review).
                    "no_eligible_products": insufficient,
                    "guideline_exception_required": not insufficient,
                },
                proposed_outcome=va_outcome,
                confidence=0.8,
                signals=[
                    make_signal("loan_type", "VA"),
                    make_signal("va_entitlement_used", va_used),
                    make_signal("va_entitlement_remaining", va_remaining),
                ],
                contradictions=[],
                hypothesis=(
                    "VA loans require COE verification; second-use entitlement "
                    "escalates and insufficient remaining entitlement blocks."
                ),
                conclusion=(
                    f"VA loan: entitlement_used={va_used}, remaining={va_remaining}, "
                    f"loan_amount={loan_amt:.0f} -> {va_outcome.value}"
                ),
                confidence_basis="VA entitlement math is deterministic given COE values.",
                summary=f"VA eligibility: {va_outcome.value} (entitlement_used={va_used}).",
            )

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

        # ── CO-C: collateral resolvers (CO-A property + CO-B appraisal) ──
        # Reads property_type/usage/purchase_price/appraised_value from the
        # Application object. Branches only escalate to BLOCK/ESCALATE, never
        # relax. (Policy engine still has the last word on outcome.)
        app = first_object(bundle, "Application") or {}

        def _f(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return 0.0

        # RA-4C: catalogue-resolved collateral rules injected via the bundle
        # (the runner loaded them through rule_loader; resolvers stay sync).
        collateral_obj = first_object(bundle, "collateral_rules") or {}
        collateral_values = collateral_obj.get("values")
        # RA-5A: workbench three-layer disclosure per rule.
        from core.catalogue.rule_loader import expand_rule_traces
        collateral_rule_trace = expand_rule_traces(collateral_obj.get("trace"))

        prop_result = PropertyEligibilityResolver(collateral_values).resolve(
            property_type=app.get("property_type") or "sfr",
            usage_type=app.get("usage_type") or "primary",
        )
        appr_result = AppraisalAnalyzer(collateral_values).analyze(
            appraised_value=_f(app.get("appraised_value")),
            purchase_price=_f(app.get("purchase_price")),
            loan_amount=_f(app.get("loan_amount")),
        )

        collateral_conditions = (
            prop_result.conditions + appr_result.conditions
        )
        collateral_reason = ""

        if not prop_result.fannie_eligible:
            outcome = DecisionOutcome.BLOCK
            collateral_reason = (
                " Property ineligible: "
                + "; ".join(prop_result.ineligibility_reasons)
            )
        elif appr_result.status == "major_gap" and outcome in (
            DecisionOutcome.ALLOW, DecisionOutcome.RECOMMEND
        ):
            outcome = DecisionOutcome.ESCALATE
            collateral_reason = (
                f" Appraisal gap: ${appr_result.gap_amount:,.0f} "
                f"({appr_result.gap_pct:.1f}%)."
            )

        # ── RA-PERSONA-B: evidence quality (advisory, OUTCOME-NEUTRAL) ────
        # Eligibility depends on accurate property/collateral evidence. Raise
        # QUALITY signals + provenance but do NOT move the catalogue/collateral-
        # driven outcome above — so 16/16 holds. Threshold is the catalogue
        # documentation-confidence floor (Fannie B3-3.1-01, governed_by=agency)
        # on every bundle; the constant is a catalogue-unreachable safety net.
        ev = first_object(bundle, "evidence") or {}
        evidence_populated = bool(ev.get("evidence_populated"))
        evidence_any_conflicts = bool(ev.get("evidence_any_conflicts"))
        evidence_overall_conf = ev.get("evidence_overall_confidence")
        evidence_threshold_trace = ev.get("income_confidence_threshold_trace")
        if ev and not evidence_populated:
            signals.append(make_signal(
                "PRODUCT_MISSING_PROPERTY_DOCS", True,
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=("No evidence facts on file — eligibility cannot be "
                       "confirmed from documentary evidence. Obtain property "
                       "and qualifying documents."),
            ))
        elif evidence_populated and evidence_any_conflicts:
            signals.append(make_signal(
                "PRODUCT_EVIDENCE_CONFLICT", True,
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=("Evidence conflict on file — verify the property/"
                       "qualifying data before confirming eligibility."),
            ))

        return OfflineReasoning(
            output_payload={
                "eligible_products": eligible,
                "guideline_exceptions_required": exceptions_required,
                "no_eligible_products": not eligible,
                "no_guideline_exceptions_required": not exceptions_required,
                "eligible_with_exceptions": bool(exceptions_required),
                "guideline_exception_required": bool(exceptions_required),
                # RA-PERSONA-B: evidence provenance behind eligibility (advisory).
                "evidence_populated": evidence_populated,
                "product_evidence_confidence": (
                    round(float(evidence_overall_conf), 3)
                    if evidence_overall_conf is not None else None
                ),
                "product_evidence_conflicts": evidence_any_conflicts,
                "product_evidence_governed_by": (
                    (evidence_threshold_trace or {}).get("governed_by")
                ),
                "evidence_threshold_trace": evidence_threshold_trace,
                # CO-C additions
                "collateral_conditions": collateral_conditions,
                "appraisal_status": appr_result.status,
                "property_eligible": prop_result.fannie_eligible,
                "appraisal_gap": appr_result.gap_amount,
                # RA-4C: catalogue provenance per collateral rule.
                "collateral_rule_trace": collateral_rule_trace,
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
                + collateral_reason
            ),
        )


__all__ = ["ProductEligibilityAgent"]
