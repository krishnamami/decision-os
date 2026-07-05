from __future__ import annotations

from typing import Optional

from core.compliance.adverse_action_engine import AdverseActionEngine
from core.compliance.hmda_lar import HMDALARGenerator
from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, first_object, make_signal, upstream_payload


_UPSTREAM_DECISIONS = (
    "income_verification",
    "credit_assessment",
    "fraud_screening",
    "dti_calculation",
    "ltv_assessment",
    "product_eligibility",
)


class SeniorUnderwritingAgent(LendingPersona):
    """underwriting_decision — synthesise everything upstream.

    Highest-stakes decision in the pipeline. Boundary keys:
      all_upstream_auto_cleared, risk_score, no_exceptions_required,
      any_upstream_hard_block, fraud_screening.decision,
      senior_underwriter_review_required."""

    DEFAULT_AGENT_ID = "senior_underwriting_agent_v1"

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="senior_underwriting_agent",
            decision_id="underwriting_decision",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        per_upstream: dict[str, dict] = {
            d: bundle.upstream_outputs.get(d) or {} for d in _UPSTREAM_DECISIONS
        }
        outcomes = {d: (per_upstream[d].get("outcome") or "missing") for d in _UPSTREAM_DECISIONS}

        # Per-tenant UW risk thresholds from overlay_rules (ContextEnricher.
        # _attach_uw_thresholds injects them); fall back to the hardcoded defaults.
        ev = first_object(bundle, "evidence") or {}

        def _t(key, default):
            v = ev.get(key)
            return default if v is None else float(v)

        auto_max = _t("uw_auto_approve_risk_max", 0.25)
        escalate_min = _t("uw_escalate_risk_min", 0.60)

        any_block = any(o == "block" for o in outcomes.values())
        all_auto_cleared = all(o == "allow" for o in outcomes.values())
        any_escalate_or_recommend = any(
            o in ("escalate", "recommend") for o in outcomes.values()
        )

        # Risk score: 1.0 if any upstream blocked, else weighted
        # combination of upstream non-allow outcomes. Crude but
        # adequate for the boundary.
        if any_block:
            risk_score = 1.0
        else:
            non_allow = sum(1 for o in outcomes.values() if o != "allow")
            risk_score = min(1.0, 0.10 + 0.15 * non_allow)

        senior_review_required = (
            risk_score > escalate_min
            or any_escalate_or_recommend
        )

        # Fraud-specific signal expected by boundary `fraud_screening.decision`.
        fraud_outcome = outcomes.get("fraud_screening")

        signals = [
            make_signal(
                "all_upstream_auto_cleared",
                all_auto_cleared,
                direction=(
                    SignalDirection.SUPPORTS
                    if all_auto_cleared
                    else SignalDirection.CONTRADICTS
                ),
                weight=2.0,
            ),
            make_signal(
                "risk_score",
                round(risk_score, 3),
                direction=(
                    SignalDirection.CONTRADICTS
                    if risk_score > escalate_min
                    else SignalDirection.NEUTRAL
                ),
                weight=2.0,
            ),
            make_signal("any_upstream_hard_block", any_block),
            make_signal("fraud_screening.decision", fraud_outcome),
            make_signal(
                "senior_underwriter_review_required", senior_review_required
            ),
        ]

        if any_block or fraud_outcome == "block":
            outcome = DecisionOutcome.BLOCK
            confidence = 0.95
        elif all_auto_cleared and risk_score <= auto_max:
            outcome = DecisionOutcome.ALLOW
            confidence = 0.85
        elif risk_score <= escalate_min:
            outcome = DecisionOutcome.RECOMMEND
            confidence = 0.7
        else:
            outcome = DecisionOutcome.ESCALATE
            confidence = 0.6

        underwriting_outcome = {
            DecisionOutcome.ALLOW: "approve",
            DecisionOutcome.RECOMMEND: "conditional_approve",
            DecisionOutcome.ESCALATE: "conditional_approve",
            DecisionOutcome.BLOCK: "decline",
        }[outcome]

        # ── RA-PERSONA-C: evidence quality (advisory, OUTCOME-NEUTRAL) ────
        # The final decision must surface the full evidence picture. Append
        # QUALITY signals + provenance; never move proposed_outcome → 16/16 holds.
        # Threshold is the catalogue documentation-confidence floor (Fannie
        # B3-3.1-01, governed_by=agency); the constant is a safety net only.
        # (ev was resolved above for the risk thresholds.)
        evidence_populated = bool(ev.get("evidence_populated"))
        evidence_any_conflicts = bool(ev.get("evidence_any_conflicts"))
        evidence_overall_conf = ev.get("evidence_overall_confidence")
        conf_min = ev.get("income_confidence_min")
        if conf_min is None:
            conf_min = 0.75
        evidence_threshold_trace = ev.get("income_confidence_threshold_trace")
        if evidence_populated and evidence_any_conflicts:
            signals.append(make_signal(
                "UW_EVIDENCE_CONFLICTS", True,
                direction=SignalDirection.CONTRADICTS, source="evidence", weight=2.0,
                notes=("Evidence conflicts across the file — the final decision "
                       "should surface them for senior review."),
            ))
        if (evidence_populated and evidence_overall_conf is not None
                and evidence_overall_conf < conf_min):
            signals.append(make_signal(
                "UW_LOW_EVIDENCE", round(float(evidence_overall_conf), 3),
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=(f"Overall evidence confidence {evidence_overall_conf:.0%} "
                       f"below {conf_min:.0%} (Fannie B3-3.1-01)."),
            ))

        # ── RA-7B: Adverse Action Notice (ECOA / Reg B §1002.9) ──────────
        # Only a decline (BLOCK) is an adverse action — escalate/recommend are
        # not. Builds notice DATA (HMDA denial codes + 30-day deadline from the
        # catalogue) from the upstream decisions that blocked. ADVISORY artifact
        # in output_payload; proposed_outcome is untouched → 16/16 holds.
        adverse_action = None
        if outcome == DecisionOutcome.BLOCK:
            blocking = [d for d, o in outcomes.items() if o == "block"]
            engine = AdverseActionEngine(
                rules={"adverse_action_days_max": ev.get("adverse_action_days_max")}
            )
            adverse_action = engine.generate_notice(
                bundle.application_id, blocking,
                credit_bureau_used="credit_assessment" in _UPSTREAM_DECISIONS,
            )
            signals.append(make_signal(
                "ADVERSE_ACTION_REQUIRED", adverse_action["hmda_denial_codes"],
                direction=SignalDirection.CONTRADICTS, source="adverse_action",
                notes=(f"Decline -> ECOA adverse-action notice due within "
                       f"{adverse_action['days_to_notice']} days; HMDA codes "
                       f"{adverse_action['hmda_denial_codes']} "
                       f"(Reg B §1002.9)."),
            ))

        # ── RA-7C: HMDA LAR record (Reg C, 12 CFR Part 1003) ─────────────
        # One LAR record per application. Demographic data (ethnicity/race/sex/
        # age) is COLLECTED + REPORTED but NEVER used here — the record is built
        # AFTER the outcome is set, purely from data the enricher surfaced.
        # Advisory artifact; proposed_outcome untouched → 16/16 holds.
        hmda_fields = ev.get("hmda_fields") or {}
        hmda_lar = HMDALARGenerator().generate_lar_record(
            bundle.application_id, hmda_fields,
            outcome=outcome.value,
            adverse_action=adverse_action,
            tenant_id=hmda_fields.get("tenant_id"),
            decision_date=(adverse_action or {}).get("decision_date"),
        )

        return OfflineReasoning(
            output_payload={
                "underwriting_outcome": underwriting_outcome,
                # RA-7B — adverse-action notice data (None unless declined).
                "adverse_action": adverse_action,
                "adverse_action_rule_trace": ev.get("adverse_action_rule_trace"),
                # RA-7C — HMDA LAR record (always present; advisory).
                "hmda_lar": hmda_lar,
                # RA-PERSONA-C: evidence provenance (advisory).
                "evidence_populated": evidence_populated,
                "uw_evidence_confidence": (
                    round(float(evidence_overall_conf), 3)
                    if evidence_overall_conf is not None else None
                ),
                "uw_evidence_conflicts": evidence_any_conflicts,
                "uw_evidence_governed_by": (
                    (evidence_threshold_trace or {}).get("governed_by")
                ),
                "evidence_threshold_trace": evidence_threshold_trace,
                "risk_score": round(risk_score, 3),
                "all_upstream_auto_cleared": all_auto_cleared,
                "any_upstream_hard_block": any_block,
                "no_exceptions_required": all_auto_cleared,
                "senior_underwriter_review_required": senior_review_required,
                "exceptions_required": [
                    d for d, o in outcomes.items() if o not in ("allow", "missing")
                ],
                "upstream_outcomes": outcomes,
            },
            proposed_outcome=outcome,
            confidence=confidence,
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Auto-approval requires every upstream decision to have "
                "cleared cleanly; any block hard-fails; soft signals route "
                "to recommend or escalate based on aggregated risk."
            ),
            conclusion=(
                f"all_clean={all_auto_cleared}, any_block={any_block}, "
                f"risk_score={risk_score:.2f} → {outcome.value} "
                f"({underwriting_outcome})"
            ),
            confidence_basis=(
                "Confidence is highest on a clean sweep or a clear hard "
                "block; lower on soft mixed signals where senior review "
                "is the right answer."
            ),
            summary=(
                f"Underwriting outcome {underwriting_outcome!r} "
                f"(risk_score {risk_score:.2f}) — proposed {outcome.value}."
            ),
        )


__all__ = ["SeniorUnderwritingAgent"]
