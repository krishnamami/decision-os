from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, first_object, make_signal, upstream_payload


# P0-D — every pricing input is now data-driven: base_rate from rate_sheet_entry,
# the LLPA coefficients + band/review thresholds from agency_guidelines, and the
# usury cap from regulatory_rules — all resolved by ContextEnricher._attach_pricing
# and read off the bundle's "evidence" object. These module constants are ONLY the
# crash-guard fallback (they match the catalogue seeds / SAFE_DEFAULTS) so a missing
# row can never break pricing.
_BASE_RATE = 0.0625                  # <- rate_sheet_entry (tenant product par)
_LLPA_CREDIT_PER_POINT = 0.0005      # <- llpa_credit_score_below_700_per_point
_LLPA_LTV_PER_POINT = 0.05           # <- llpa_ltv_above_80_per_point
_LLPA_DTI_PER_POINT = 0.02           # <- llpa_dti_above_36_per_point
_LLPA_NON_QM_ADD_ON = 0.0125         # <- llpa_non_qm_add_on
_RATE_NORMAL_BAND_MAX = 0.10         # <- rate_normal_band_max
_LLPA_MANUAL_REVIEW = 0.02           # <- llpa_manual_review_threshold
_USURY_LIMIT_FALLBACK = 0.18         # <- regulatory_rules state usury cap (federal fallback)


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

        # P0-D — pull every pricing input from the catalogue values the enricher
        # resolved onto the bundle; the module constants are only the crash guard.
        ev = first_object(bundle, "evidence") or {}

        def _pv(key: str, default: float) -> float:
            v = ev.get(key)
            return default if v is None else float(v)

        base_rate = _pv("pricing_base_rate", _BASE_RATE)
        c_credit = _pv("pricing_llpa_credit_per_point", _LLPA_CREDIT_PER_POINT)
        c_ltv = _pv("pricing_llpa_ltv_per_point", _LLPA_LTV_PER_POINT)
        c_dti = _pv("pricing_llpa_dti_per_point", _LLPA_DTI_PER_POINT)
        c_non_qm = _pv("pricing_llpa_non_qm_add_on", _LLPA_NON_QM_ADD_ON)
        normal_band_max = _pv("pricing_rate_normal_band_max", _RATE_NORMAL_BAND_MAX)
        manual_review_max = _pv("pricing_llpa_manual_review_threshold", _LLPA_MANUAL_REVIEW)
        usury_limit = _pv("pricing_usury_limit", _USURY_LIMIT_FALLBACK)

        # LLPA add-ons: higher LTV / lower score / higher DTI bumps rate. The
        # per-point coefficients + non-QM add-on now come from agency_guidelines.
        llpa = 0.0
        if score < 700:
            llpa += (700 - score) * c_credit
        if ltv > 0.80:
            llpa += (ltv - 0.80) * c_ltv
        if dti > 0.36:
            llpa += (dti - 0.36) * c_dti
        if loan_type == "non_qm":
            llpa += c_non_qm

        rate = base_rate + llpa
        rate_within_normal_band = rate <= normal_band_max
        manual_adjustments_required = llpa > manual_review_max
        pricing_exception_possible = manual_adjustments_required and rate <= normal_band_max
        usury_violation = rate > usury_limit
        concurrent_lock_conflict = bool(loan.get("concurrent_rate_lock_conflict") or False)

        signals = [
            make_signal("base_rate", round(base_rate, 4)),
            make_signal(
                "llpa",
                round(llpa, 4),
                direction=(
                    SignalDirection.CONTRADICTS
                    if llpa > manual_review_max
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

        # ── RA-PERSONA-C: evidence quality (advisory, OUTCOME-NEUTRAL) ────
        # Pricing is less reliable on weak evidence. Append a QUALITY signal +
        # provenance; never move proposed_outcome → 16/16 holds. Threshold is the
        # catalogue documentation-confidence floor (Fannie B3-3.1-01,
        # governed_by=agency); the constant is a safety net only.
        ev = first_object(bundle, "evidence") or {}
        evidence_populated = bool(ev.get("evidence_populated"))
        evidence_any_conflicts = bool(ev.get("evidence_any_conflicts"))
        evidence_overall_conf = ev.get("evidence_overall_confidence")
        conf_min = ev.get("income_confidence_min")
        if conf_min is None:
            conf_min = 0.75
        evidence_threshold_trace = ev.get("income_confidence_threshold_trace")
        if (evidence_populated and evidence_overall_conf is not None
                and evidence_overall_conf < conf_min):
            signals.append(make_signal(
                "PRICING_LOW_CONFIDENCE", round(float(evidence_overall_conf), 3),
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=(f"Pricing rests on low-confidence evidence "
                       f"{evidence_overall_conf:.0%} (< {conf_min:.0%}, Fannie "
                       "B3-3.1-01) — treat the rate as less reliable."),
            ))

        return OfflineReasoning(
            output_payload={
                "interest_rate": round(rate, 4),
                "llpa": round(llpa, 4),
                # P0-D — pricing provenance: which inputs came from the catalogue
                # vs the crash-guard constant, for the workbench disclosure.
                "base_rate": round(base_rate, 4),
                "usury_limit": round(usury_limit, 4),
                "pricing_base_rate_governed_by": ev.get("pricing_base_rate_governed_by") or "safe_default",
                "pricing_usury_governed_by": ev.get("pricing_usury_governed_by") or "safe_default",
                "pricing_property_state": ev.get("pricing_property_state"),
                "pricing_rule_traces": ev.get("pricing_rule_traces"),
                # RA-PERSONA-C: evidence provenance (advisory).
                "evidence_populated": evidence_populated,
                "pricing_evidence_confidence": (
                    round(float(evidence_overall_conf), 3)
                    if evidence_overall_conf is not None else None
                ),
                "pricing_evidence_conflicts": evidence_any_conflicts,
                "pricing_evidence_governed_by": (
                    (evidence_threshold_trace or {}).get("governed_by")
                ),
                "evidence_threshold_trace": evidence_threshold_trace,
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
