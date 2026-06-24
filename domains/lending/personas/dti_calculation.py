from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.obligations.obligation_resolver import ObligationResolver
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

        # ── RA-PERSONA-B: evidence quality (advisory, OUTCOME-NEUTRAL) ────
        # DTI is only as reliable as the income evidence it rests on. Raise
        # QUALITY signals + provenance but do NOT move the dti/income-confidence-
        # driven outcome above — so 16/16 holds. Threshold is the catalogue
        # documentation-confidence floor (income_documentation_confidence_min,
        # Fannie B3-3.1-01, governed_by=agency) the enricher attaches to every
        # bundle; the constant is a catalogue-unreachable safety net only.
        ev = latest_object(bundle, "evidence") or {}
        evidence_populated = bool(ev.get("evidence_populated"))
        ev_income_conf = ev.get("ev_income_confidence")
        ev_income_conflicts = bool(ev.get("ev_income_conflicts"))
        conf_min = ev.get("income_confidence_min")
        if conf_min is None:
            conf_min = 0.75
        evidence_threshold_trace = ev.get("income_confidence_threshold_trace")
        if evidence_populated and ev_income_conflicts:
            signals.append(make_signal(
                "DTI_INCOME_CONFLICT", True,
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=("Income evidence conflict across documents — DTI "
                       "reliability affected. UW review of the income basis."),
            ))
        if (evidence_populated and ev_income_conf is not None
                and ev_income_conf < conf_min):
            signals.append(make_signal(
                "DTI_INCOME_LOW_CONFIDENCE", round(float(ev_income_conf), 3),
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=(f"DTI rests on low-confidence income evidence "
                       f"{ev_income_conf:.0%} (< {conf_min:.0%}, Fannie "
                       "B3-3.1-01). Treat the ratio as uncertain."),
            ))

        # ── OB-A: obligation breakdown (ADVISORY, additive) ───────────────
        # Decompose monthly obligations by type for the UW workbench. Reads the
        # catalogue obligation rules injected by the runner; routes each item
        # (student loans pre-computed by tradeline_analyzer, alimony/child-support
        # paid via the INC-F resolver, installment/revolving/heloc calculators).
        # output_payload ONLY — dti/dti_front/dti_back + total_obligations above
        # are UNCHANGED (changing the DTI math is a later OB slice). Meridian's
        # dti bundle carries only the aggregate existing_debt_obligations (no
        # per-type list), so the breakdown is foundation there; live per-obligation
        # inputs (tradelines/decree) flow on PATH 2.
        obligation_rules_obj = latest_object(bundle, "obligation_rules") or {}
        obligation_rule_values = obligation_rules_obj.get("values")
        obligations_input = application.get("obligations") or []
        obligation_breakdown = ObligationResolver(
            rules=obligation_rule_values).resolve(obligations_input)
        obligation_breakdown["aggregate_existing_debt_monthly"] = round(
            existing_debt_monthly, 2)
        obligation_breakdown["rule_trace"] = obligation_rules_obj.get("trace")
        obligation_breakdown["note"] = (
            "Advisory breakdown — DTI ratio unchanged. Per-obligation inputs "
            "(tradelines, decree) populate on PATH 2; meridian carries only the "
            "aggregate existing_debt_obligations."
        )

        return OfflineReasoning(
            output_payload={
                "dti_ratio": round(dti, 3) if dti != float("inf") else None,
                # OB-A — advisory obligation breakdown (additive).
                "obligation_breakdown": obligation_breakdown,
                "dti": round(dti, 3) if dti != float("inf") else None,
                "verified_income": verified_income_annual,
                "monthly_obligations": round(total_obligations, 2),
                "monthly_income": round(monthly_income, 2),
                # RA-PERSONA-B: income-evidence provenance behind the DTI (advisory).
                "evidence_populated": evidence_populated,
                "dti_income_evidence_confidence": (
                    round(float(ev_income_conf), 3)
                    if ev_income_conf is not None else None
                ),
                "dti_income_evidence_conflicts": ev_income_conflicts,
                "dti_income_evidence_governed_by": (
                    (evidence_threshold_trace or {}).get("governed_by")
                ),
                "evidence_threshold_trace": evidence_threshold_trace,
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
