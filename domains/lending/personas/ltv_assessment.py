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

        # ── RA-PERSONA-B: evidence quality (advisory, OUTCOME-NEUTRAL) ────
        # LTV rests on the appraised value; weak/conflicting collateral evidence
        # makes the ratio itself uncertain. ev_asset_confidence is the proxy for
        # appraisal/collateral evidence quality. Raise QUALITY signals +
        # provenance but do NOT move the ltv-driven outcome above — so 16/16
        # holds. Threshold is the catalogue documentation-confidence floor
        # (Fannie B3-3.1-01, governed_by=agency) on every bundle; the constant
        # is a catalogue-unreachable safety net only.
        ev = first_object(bundle, "evidence") or {}
        evidence_populated = bool(ev.get("evidence_populated"))
        ev_asset_conf = ev.get("ev_asset_confidence")
        evidence_any_conflicts = bool(ev.get("evidence_any_conflicts"))
        conf_min = ev.get("income_confidence_min")
        if conf_min is None:
            conf_min = 0.75
        evidence_threshold_trace = ev.get("income_confidence_threshold_trace")
        if evidence_populated and evidence_any_conflicts:
            signals.append(make_signal(
                "LTV_EVIDENCE_CONFLICT", True,
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=("Evidence conflict on file — collateral/LTV basis should "
                       "be reviewed alongside the appraisal."),
            ))
        if (evidence_populated and ev_asset_conf is not None
                and ev_asset_conf < conf_min):
            signals.append(make_signal(
                "LTV_EVIDENCE_WEAK", round(float(ev_asset_conf), 3),
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=(f"LTV rests on low-confidence collateral evidence "
                       f"{ev_asset_conf:.0%} (< {conf_min:.0%}, Fannie "
                       "B3-3.1-01). Treat the ratio as uncertain."),
            ))

        return OfflineReasoning(
            output_payload={
                "ltv_ratio": round(ltv, 3) if ltv != float("inf") else None,
                "ltv": round(ltv, 3) if ltv != float("inf") else None,
                "max_allowable_ltv": max_ltv,
                "appraised_value": appraised,
                "loan_amount": loan_amount,
                "appraisal_disputed": appraisal_disputed,
                # RA-PERSONA-B: collateral-evidence provenance behind LTV (advisory).
                "evidence_populated": evidence_populated,
                "ltv_evidence_confidence": (
                    round(float(ev_asset_conf), 3)
                    if ev_asset_conf is not None else None
                ),
                "ltv_evidence_conflicts": evidence_any_conflicts,
                "ltv_evidence_governed_by": (
                    (evidence_threshold_trace or {}).get("governed_by")
                ),
                "evidence_threshold_trace": evidence_threshold_trace,
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
