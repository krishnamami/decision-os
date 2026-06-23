from __future__ import annotations

from typing import Optional

from core.compliance.atr_verifier import ATRVerifier
from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, first_object, make_signal


class ComplianceAgent(LendingPersona):
    """compliance_check — HMDA, ECOA / fair-lending, state rules,
    TRID. High-risk; blocks closing if it blocks."""

    DEFAULT_AGENT_ID = "compliance_agent_v1"

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="compliance_agent",
            decision_id="compliance_check",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        compliance = first_object(bundle, "ComplianceRecord") or {}
        hmda_complete = bool(compliance.get("all_hmda_fields_complete") or False)
        fair_lending_violation = bool(compliance.get("fair_lending_violation") or False)
        missing_disclosures = bool(compliance.get("missing_required_disclosures") or False)
        state_rules_passed = bool(compliance.get("state_rules_passed") or False)
        cd_timing_compliant = bool(compliance.get("cd_timing_compliant") or False)
        regulatory_ambiguity = bool(compliance.get("regulatory_ambiguity") or False)
        mixed_jurisdiction = bool(compliance.get("mixed_jurisdiction") or False)
        # State rules applied per property location (PROMPT C).
        applicable_state_rules = compliance.get("applicable_state_rules") or []
        property_state = compliance.get("property_state") or ""
        state_rule_count = len(applicable_state_rules)

        # TX Constitution Art. XVI 50(a)(6): a cash-out refinance on a Texas
        # homestead is capped at 80% LTV. Over that is a hard state-rule
        # violation -> block. property_state / loan_purpose / ltv are surfaced
        # onto the ComplianceRecord from loan_terms by EdmsContextStore.
        loan_purpose = compliance.get("loan_purpose") or ""
        try:
            ltv_pct = float(compliance.get("ltv") or 0)
        except (TypeError, ValueError):
            ltv_pct = 0.0
        tx_cashout_ltv_violation = (
            str(property_state).upper() == "TX"
            and str(loan_purpose) == "cash_out_refinance"
            and ltv_pct > 80.0
        )
        if tx_cashout_ltv_violation:
            state_rules_passed = False

        signals = [
            make_signal(
                "all_hmda_fields_complete",
                hmda_complete,
                direction=(
                    SignalDirection.SUPPORTS
                    if hmda_complete
                    else SignalDirection.CONTRADICTS
                ),
            ),
            make_signal("fair_lending_violation", fair_lending_violation),
            make_signal("missing_required_disclosures", missing_disclosures),
            make_signal("state_rules_passed", state_rules_passed),
            make_signal("cd_timing_compliant", cd_timing_compliant),
        ]

        if fair_lending_violation or missing_disclosures or tx_cashout_ltv_violation:
            outcome = DecisionOutcome.BLOCK
            confidence = 0.95
        elif regulatory_ambiguity or mixed_jurisdiction:
            outcome = DecisionOutcome.ESCALATE
            confidence = 0.6
        elif hmda_complete and state_rules_passed:
            outcome = DecisionOutcome.ALLOW
            confidence = 0.9
        else:
            outcome = DecisionOutcome.RECOMMEND
            confidence = 0.7

        # decisions.yaml uses a `no_fair_lending_flags` boundary token.
        no_fair_lending_flags = not fair_lending_violation
        minor_data_gap = not hmda_complete and not missing_disclosures

        # ── RA-PERSONA-C: evidence quality (advisory, OUTCOME-NEUTRAL) ────
        # Append QUALITY signals + provenance; never move proposed_outcome → 16/16
        # holds. Threshold is the catalogue documentation-confidence floor (Fannie
        # B3-3.1-01, governed_by=agency); the constant is a safety net only.
        ev = first_object(bundle, "evidence") or {}
        evidence_populated = bool(ev.get("evidence_populated"))
        ev_income_conf = ev.get("ev_income_confidence")
        ev_credit_conf = ev.get("ev_credit_confidence")
        evidence_any_conflicts = bool(ev.get("evidence_any_conflicts"))
        conf_min = ev.get("income_confidence_min")
        if conf_min is None:
            conf_min = 0.75
        evidence_threshold_trace = ev.get("income_confidence_threshold_trace")
        if (evidence_populated and ev_income_conf is not None
                and ev_income_conf < conf_min):
            signals.append(make_signal(
                "COMPLIANCE_INCOME_UNCERTAIN", round(float(ev_income_conf), 3),
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=(f"Income evidence confidence {ev_income_conf:.0%} below "
                       f"{conf_min:.0%} (Fannie B3-3.1-01) — QC review."),
            ))
        if (evidence_populated and ev_credit_conf is not None
                and ev_credit_conf < conf_min):
            signals.append(make_signal(
                "COMPLIANCE_CREDIT_UNCERTAIN", round(float(ev_credit_conf), 3),
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=(f"Credit evidence confidence {ev_credit_conf:.0%} below "
                       f"{conf_min:.0%} (Fannie B3-3.1-01) — QC review."),
            ))
        if evidence_populated and evidence_any_conflicts:
            signals.append(make_signal(
                "COMPLIANCE_EVIDENCE_CONFLICT", True,
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes="Evidence conflict on file — compliance QC should review.",
            ))

        # ── RA-7A: ATR / QM (12 CFR 1026.43) — advisory, OUTCOME-NEUTRAL ──
        # Thresholds from the catalogue (enricher _attach_atr_qm); the 8 ATR
        # factors from entity_states (enricher _attach_atr_factors — the
        # compliance view carries only ltv). Signals NEVER move proposed_outcome
        # → 16/16 holds. A genuinely NULL factor (e.g. SC03 has no dti_back)
        # raises a CONTRADICTS quality signal, not a block.
        atr_entity = dict(ev.get("atr_entity") or {})
        atr_entity["employment_verified"] = bool(
            ev.get("evidence_employment_status")
            or ev.get("ev_employment_confidence")
        )
        atr_rules = {
            "atr_required_factors": ev.get("atr_required_factors"),
            "qm_dti_max":           ev.get("qm_dti_max"),
            "qm_points_fees_max":   ev.get("qm_points_fees_max"),
            "hpml_threshold_bps":   ev.get("hpml_threshold_bps"),
        }
        verifier = ATRVerifier(rules=atr_rules)
        atr_result = verifier.verify(atr_entity)
        qm_result = verifier.classify_qm(atr_entity)
        atr_loaded = bool(ev.get("atr_entity"))

        if atr_loaded and atr_result["atr_satisfied"]:
            signals.append(make_signal(
                "ATR_SATISFIED", atr_result["factors_passed"],
                direction=SignalDirection.SUPPORTS, source="atr_verifier",
                notes=(f"All {atr_result['factors_checked']} ATR factors verified "
                       f"(12 CFR 1026.43(c))."),
            ))
        elif atr_loaded:
            signals.append(make_signal(
                "ATR_FACTOR_MISSING", atr_result["factors_failed"],
                direction=SignalDirection.CONTRADICTS, source="atr_verifier",
                notes=(f"ATR factors not verified: {atr_result['factors_failed']} "
                       f"(12 CFR 1026.43(c)) — advisory; resolve before "
                       f"consummation."),
            ))

        qm_class = qm_result["qm_classification"]
        if atr_loaded and qm_class == "NON_QM":
            signals.append(make_signal(
                "NON_QM_LOAN", qm_class,
                direction=SignalDirection.CONTRADICTS, source="atr_verifier",
                notes=("Loan fails QM criteria (12 CFR 1026.43(e)); ATR must be "
                       "proven case-by-case. Advisory — outcome unchanged."),
            ))
        elif atr_loaded:
            signals.append(make_signal(
                qm_class, qm_class,
                direction=SignalDirection.SUPPORTS, source="atr_verifier",
                notes=f"{qm_class} (12 CFR 1026.43(e)).",
            ))

        return OfflineReasoning(
            output_payload={
                "compliance_cleared": outcome == DecisionOutcome.ALLOW,
                # RA-PERSONA-C: evidence provenance (advisory).
                "evidence_populated": evidence_populated,
                "compliance_income_evidence_confidence": (
                    round(float(ev_income_conf), 3)
                    if ev_income_conf is not None else None
                ),
                "compliance_credit_evidence_confidence": (
                    round(float(ev_credit_conf), 3)
                    if ev_credit_conf is not None else None
                ),
                "compliance_evidence_conflicts": evidence_any_conflicts,
                "compliance_evidence_governed_by": (
                    (evidence_threshold_trace or {}).get("governed_by")
                ),
                "evidence_threshold_trace": evidence_threshold_trace,
                "all_hmda_fields_complete": hmda_complete,
                "no_fair_lending_flags": no_fair_lending_flags,
                "state_rules_passed": state_rules_passed,
                "minor_data_gap": minor_data_gap,
                "fair_lending_violation": fair_lending_violation,
                "missing_required_disclosures": missing_disclosures,
                "regulatory_ambiguity": regulatory_ambiguity,
                "mixed_jurisdiction": mixed_jurisdiction,
                "applicable_state_rules": applicable_state_rules,
                "property_state": property_state,
                "state_rule_count": state_rule_count,
                # Exposed so the decisions.yaml boundary block_if can match it
                # (the policy engine evaluates against output_payload).
                "tx_cashout_ltv_violation": tx_cashout_ltv_violation,
                # RA-7A — ATR/QM disclosure (advisory; never gates the outcome).
                "atr_evaluated": atr_loaded,
                "atr_satisfied": atr_result["atr_satisfied"] if atr_loaded else None,
                "atr_factors_passed": atr_result["factors_passed"] if atr_loaded else None,
                "atr_factors_checked": atr_result["factors_checked"],
                "atr_factors_failed": atr_result["factors_failed"] if atr_loaded else None,
                "atr_citation": atr_result["citation"],
                "qm_classification": qm_class if atr_loaded else None,
                "safe_harbor_protected": qm_result["safe_harbor_protected"] if atr_loaded else None,
                "qm_dti_check": qm_result["dti_check"] if atr_loaded else None,
                "qm_points_fees_check": qm_result["points_fees_check"] if atr_loaded else None,
                "qm_hpml_flag": qm_result["hpml_flag"] if atr_loaded else None,
                "qm_citation": qm_result["citation"],
                "atr_qm_rule_traces": ev.get("atr_qm_rule_traces"),
            },
            proposed_outcome=outcome,
            confidence=confidence,
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Application is compliant when all HMDA fields are present, "
                "no fair-lending flags exist, and state rules pass."
            ),
            conclusion=(
                f"hmda_complete={hmda_complete}, fair_lending_violation="
                f"{fair_lending_violation}, missing_disclosures="
                f"{missing_disclosures}, state_rules_passed={state_rules_passed} "
                f"({property_state or 'n/a'}: {state_rule_count} rules evaluated) "
                f"→ {outcome.value}"
            ),
            confidence_basis=(
                "Hard rules drive blocks deterministically; soft ESCALATE "
                "paths reflect ambiguity in mixed-jurisdiction or unclear "
                "state-rule cases."
            ),
            summary=(
                f"Compliance posture: {outcome.value} "
                f"(hmda_complete={hmda_complete}, "
                f"fair_lending_violation={fair_lending_violation}, "
                f"state={property_state or 'n/a'}, state_rules_passed={state_rules_passed})."
            ),
        )


__all__ = ["ComplianceAgent"]
