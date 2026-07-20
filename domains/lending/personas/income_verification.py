from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.income.alimony_resolver import AlimonyChildSupportResolver
from core.income.retirement_income_resolver import RetirementIncomeResolver
from core.income.w2_income_resolver import VARIABLE_INCOME_TODO, W2IncomeResolver
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import (
    LendingPersona,
    OfflineReasoning,
    latest_object,
    make_signal,
    upstream_payload,
)


class IncomeVerificationAgent(LendingPersona):
    """income_verification — produce verified_income + income_confidence.

    Refactored (Session 11) to consume the reconciled employment
    timeline produced by `employment_reconciliation` upstream rather
    than reading raw IncomeProfile fields. The reconciliation step
    handles multi-provider divergence, employer-name normalization,
    continuity coverage, and gap detection; this persona's job is
    deciding whether the reconciled picture is good enough to
    auto-verify income.

    Inputs:
      bundle.upstream_outputs["employment_reconciliation"]["payload"]
        reconciliation_status, employer_records, comp_drift_pct,
        stated_vs_verified_drift_pct, manual_voe_required, etc.
      bundle.objects["IncomeProfile"]
        stated_income, employment_type, multiple_income_sources,
        foreign_income (still loaded by EntityHydrator from the
        IncomeDeclaredEvent + PayrollReceivedEvent merge).

    Outcome routing:
      reconciliation_status == auto_verified
                           AND no provider conflict
                           AND stated/verified within tolerance
                           AND employment_type salaried
                           → ALLOW
      reconciliation_status == partial AND no conflict
                           → ALLOW (single verified employer is enough
                             for v1; future iteration can require
                             continuity_complete for stricter products)
      reconciliation_status == conflict
                           → ESCALATE
      reconciliation_status == missing
                           → ESCALATE
      stated_vs_verified drift > 25%
                           → BLOCK
      multiple_income_sources OR foreign_income
                           → ESCALATE
    """

    DEFAULT_AGENT_ID = "income_verification_agent_v1"

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="income_verification_agent",
            decision_id="income_verification",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        # Upstream reconciliation output — the primary signal.
        reconciled = upstream_payload(bundle, "employment_reconciliation")
        reconciliation_status = reconciled.get("reconciliation_status") or "missing"
        # Fallback: read reconciliation_status from own IncomeProfile bundle
        # (populated by vw_income_verification_context from entity_states)
        if reconciliation_status == "missing":
            own_income = latest_object(bundle, "IncomeProfile") or {}
            reconciliation_status = own_income.get("reconciliation_status") or "missing"
        reconciled_attempts = int(
            reconciled.get("verification_attempts_count") or 0
        )
        reconciled_employers = reconciled.get("employer_records") or []
        comp_drift_pct = float(reconciled.get("comp_drift_pct") or 0.0)
        recon_stated_drift = float(
            reconciled.get("stated_vs_verified_drift_pct") or 0.0
        )
        manual_voe_required = bool(reconciled.get("manual_voe_required") or False)
        gap_letter_required = bool(reconciled.get("gap_letter_required") or False)
        tax_transcript_required = bool(
            reconciled.get("tax_transcript_required") or False
        )

        # Stated/verified-side data still lives on IncomeProfile —
        # employment_type, multiple_income_sources, foreign_income are
        # downstream policy levers we don't want to lose.
        income = latest_object(bundle, "IncomeProfile") or {}
        stated = float(income.get("stated_income") or 0.0)
        employment_type = income.get("employment_type") or "other"
        multiple_sources = bool(income.get("multiple_income_sources") or False)
        foreign_income = bool(income.get("foreign_income") or False)

        # Verified income is the aggregate across the reconciled
        # employer records' monthly_gross_estimate. Falls back to
        # IncomeProfile.verified_income when no reconciled records
        # exist (e.g. self-employed without payroll feed).
        verified = 0.0
        if reconciled_employers:
            for record in reconciled_employers:
                monthly = record.get("monthly_gross_estimate") or 0
                if isinstance(monthly, (int, float)):
                    verified += float(monthly) * 12
        if verified == 0.0:
            verified = float(income.get("verified_income") or 0.0)

        # Discrepancy is now the persona-level read — reconciliation
        # tracks providers vs each other; this tracks stated vs the
        # aggregated verified picture.
        if stated > 0 and verified > 0:
            discrepancy = abs(stated - verified) / stated
        else:
            discrepancy = 0.0

        # Catalogue-driven confidence scores + block threshold (ContextEnricher.
        # _attach_income_confidence injects them); fall back to the hardcoded
        # constants. The 0.05 comp-drift split + the 0.9/0.85 gates + penalties
        # below stay hardcoded (tracked as a separate future item).
        ev = latest_object(bundle, "evidence") or {}

        def _t(key, default):
            v = ev.get(key)
            return default if v is None else float(v)

        c_auto = _t("income_confidence_auto_verified", 0.95)
        c_partial = _t("income_confidence_partial", 0.82)
        c_conflict = _t("income_confidence_conflict", 0.55)
        c_missing = _t("income_confidence_missing", 0.40)
        block_pct = _t("income_discrepancy_block_pct", 0.25)

        # ── Confidence — derived from upstream status, not invented ──
        if reconciliation_status == "auto_verified":
            confidence_score = c_auto
        elif reconciliation_status == "partial":
            # Partial-but-clean (no provider conflict, stated matches
            # verified) is the common single-employer / single-provider
            # case. Worth high confidence — reconciliation didn't fail,
            # we just don't have multi-employer history. Provider
            # conflict drops it below the automate threshold.
            confidence_score = c_auto if comp_drift_pct <= 0.05 else c_partial
        elif reconciliation_status == "conflict":
            confidence_score = c_conflict
        else:  # missing
            confidence_score = c_missing
        # Penalize stated/verified divergence + non-salaried employment.
        confidence_score -= min(discrepancy, 0.3)
        if employment_type in ("self_employed", "contractor"):
            confidence_score -= 0.05
        confidence_score = max(0.0, min(1.0, confidence_score))

        # ── Outcome ─────────────────────────────────────────────────
        if discrepancy > block_pct:
            outcome = DecisionOutcome.BLOCK
        elif employment_type == "foreign_national":
            # Foreign national income requires manual UW — always escalate
            outcome = DecisionOutcome.ESCALATE
        elif employment_type == "streamline":
            # Streamline refi — no income verification needed
            outcome = DecisionOutcome.ALLOW
        elif employment_type == "retired":
            # Retired/SSA/pension — fixed income, no employment continuity needed
            # Discrepancy acceptable if income is verified
            if discrepancy > block_pct:
                outcome = DecisionOutcome.BLOCK
            elif confidence_score >= 0.85:
                outcome = DecisionOutcome.RECOMMEND  # retired always needs UW review
            else:
                outcome = DecisionOutcome.ESCALATE
        elif employment_type == "self_employed":
            # SE income requires 2yr history — always recommend for UW review
            if discrepancy > block_pct:
                outcome = DecisionOutcome.BLOCK
            elif confidence_score >= 0.75:
                outcome = DecisionOutcome.RECOMMEND
            else:
                outcome = DecisionOutcome.ESCALATE
        elif multiple_sources or foreign_income:
            outcome = DecisionOutcome.ESCALATE
        elif reconciliation_status == "missing":
            outcome = DecisionOutcome.ESCALATE
        elif reconciliation_status == "conflict":
            outcome = DecisionOutcome.ESCALATE
        elif reconciliation_status == "auto_verified" \
                and confidence_score >= 0.9 \
                and employment_type in ("salaried", "w2_salaried"):
            outcome = DecisionOutcome.ALLOW
        elif reconciliation_status in ("auto_verified", "partial") \
                and confidence_score >= 0.85:
            outcome = DecisionOutcome.ALLOW
        elif confidence_score >= 0.75:
            outcome = DecisionOutcome.RECOMMEND
        else:
            outcome = DecisionOutcome.ESCALATE

        # ── Signals ─────────────────────────────────────────────────
        signals = [
            make_signal(
                "reconciliation_status",
                reconciliation_status,
                direction=(
                    SignalDirection.SUPPORTS
                    if reconciliation_status == "auto_verified"
                    else SignalDirection.CONTRADICTS
                    if reconciliation_status in ("conflict", "missing")
                    else SignalDirection.NEUTRAL
                ),
                source="employment_reconciliation",
            ),
            make_signal(
                "verification_attempts_count",
                reconciled_attempts,
                source="employment_reconciliation",
            ),
            make_signal(
                "comp_drift_pct",
                round(comp_drift_pct, 3),
                direction=(
                    SignalDirection.CONTRADICTS
                    if comp_drift_pct > 0.10
                    else SignalDirection.NEUTRAL
                ),
                source="employment_reconciliation",
            ),
            make_signal("verified_income", verified, source="reconciliation"),
            make_signal("stated_income", stated, source="application"),
            make_signal(
                "income_confidence_score",
                round(confidence_score, 3),
                direction=(
                    SignalDirection.SUPPORTS
                    if confidence_score >= 0.9
                    else SignalDirection.NEUTRAL
                ),
            ),
            make_signal("employment_type", employment_type),
        ]
        if discrepancy > 0:
            signals.append(
                make_signal(
                    "income_discrepancy_pct",
                    round(discrepancy, 3),
                    direction=(
                        SignalDirection.CONTRADICTS
                        if discrepancy > 0.10
                        else SignalDirection.NEUTRAL
                    ),
                )
            )
        if manual_voe_required:
            signals.append(
                make_signal(
                    "manual_voe_required",
                    True,
                    direction=SignalDirection.CONTRADICTS,
                    source="employment_reconciliation",
                )
            )
        if gap_letter_required:
            signals.append(
                make_signal(
                    "gap_letter_required",
                    True,
                    direction=SignalDirection.CONTRADICTS,
                    source="employment_reconciliation",
                )
            )
        if tax_transcript_required:
            signals.append(
                make_signal(
                    "tax_transcript_required",
                    True,
                    direction=SignalDirection.CONTRADICTS,
                    source="employment_reconciliation",
                )
            )

        # ── Evidence quality (RA-3D / EV-F) ────────────────────────────
        # Read the evidence facts the enricher placed on the bundle
        # (bundle.objects["evidence"]). This is ADVISORY and OUTCOME-NEUTRAL:
        # it prefers the evidence-qualified income for the REPORTED figure
        # and raises quality flags, but does NOT move the reconciliation-
        # driven outcome or the verified_income downstream DTI consumes —
        # so 16/16 and income-sufficiency amounts are unchanged. Graceful:
        # non-meridian apps have no evidence object → stated path, no flags.
        # (ev was resolved above for the confidence thresholds.)
        evidence_populated = bool(ev.get("evidence_populated"))
        ev_income_value = ev.get("ev_income_value")
        ev_income_conf = ev.get("ev_income_confidence")
        ev_income_conflicts = bool(ev.get("ev_income_conflicts"))
        ev_income_method = ev.get("ev_income_method") or "unknown"
        ev_emp_conf = ev.get("ev_employment_confidence")
        ev_emp_conflicts = bool(ev.get("ev_employment_conflicts"))

        # Confidence thresholds come from agency_guidelines (Fannie B3-3.1-01)
        # via rule_loader, resolved by the enricher onto the bundle. The
        # constants are a safety net ONLY (catalogue-unreachable degraded
        # mode) — the governing values are the catalogue values.
        confidence_min = ev.get("income_confidence_min")
        confidence_floor = ev.get("income_confidence_floor")
        if confidence_min is None:
            confidence_min = 0.75
        if confidence_floor is None:
            confidence_floor = 0.50
        threshold_trace = ev.get("income_confidence_threshold_trace")

        # RULE 1 — prefer evidence-qualified income (reported figure only).
        income_source = "stated"
        income_method = "entity_states"
        evidence_income_confidence = None
        if (
            evidence_populated and ev_income_value
            and ev_income_conf is not None and ev_income_conf >= confidence_min
        ):
            income_source = "evidence"
            income_method = ev_income_method
            evidence_income_confidence = round(float(ev_income_conf), 3)

        # RULES 2/3/4 — quality flags as advisory CONTRADICTS signals.
        if evidence_populated and ev_income_conf is not None:
            if confidence_floor <= ev_income_conf < confidence_min:
                signals.append(make_signal(
                    "INC_LOW_CONFIDENCE", round(float(ev_income_conf), 3),
                    direction=SignalDirection.CONTRADICTS, source="evidence",
                    notes=(f"Income confidence {ev_income_conf:.0%}; method "
                           f"{ev_income_method}. Request additional docs."),
                ))
            elif ev_income_conf < confidence_floor:
                income_source = "stated"
                income_method = "entity_states"
                signals.append(make_signal(
                    "INC_VERY_LOW_CONFIDENCE", round(float(ev_income_conf), 3),
                    direction=SignalDirection.CONTRADICTS, source="evidence",
                    notes=(f"Income confidence {ev_income_conf:.0%} too low to "
                           "use evidence value. Manual verification required."),
                ))
        if ev_income_conflicts:
            signals.append(make_signal(
                "INC_CONFLICT_DETECTED", True,
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes="Income conflict across documents. Manual review required.",
            ))
        if ev_emp_conflicts:
            signals.append(make_signal(
                "EMP_CONTINUITY_CONFLICT", True,
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=(f"Employment continuity conflict; confidence "
                       f"{(ev_emp_conf or 0):.0%}. Verify employment history."),
            ))

        # ── INC-B: W2 base-income analysis (ADVISORY, output_payload only) ──
        # The W2IncomeResolver annotates the income picture with method/citation
        # and the catalogue-driven 2-year employment-history requirement for the
        # workbench. It does NOT change proposed_outcome or the verified_income
        # figure the persona reports — meridian keeps its seeded qualifying_monthly
        # (PATH 1). The doc-level resolver (qualify_from_w2_doc / qualify_from_
        # paystub) runs on the real-tenant PATH 2 once the enricher attaches
        # W2_CURRENT / PAYSTUB_CURRENT extracted_fields (not attached today —
        # ENRICHER TODO). Resolver is sync/DB-less; rules fall back to SAFE_DEFAULTS.
        # Catalogue income rules injected by the runner (_inject_decision_rules)
        # — the RA-4A pattern. Closes the catalogue→resolver loop:
        # employment_history_months_required is now read from the catalogue at
        # runtime (SAFE_DEFAULTS only as the degraded fallback). Same value (24).
        income_rules_obj = latest_object(bundle, "income_rules") or {}
        income_rule_values = income_rules_obj.get("values")
        w2_resolver = W2IncomeResolver(rules=income_rule_values)
        emp_for_history = {}
        for rec in reconciled_employers:
            if isinstance(rec, dict):
                ps = (rec.get("period_start") or rec.get("start_date")
                      or rec.get("employment_start"))
                if ps:
                    emp_for_history = {"period_start": ps}
                    break
        employment_history = w2_resolver.check_employment_history(emp_for_history)
        income_analysis = {
            "resolver": "W2IncomeResolver",
            "scope": "base salary only (W2 box1 / paystub gross)",
            "income_method": income_method,
            "qualifying_monthly_reported": verified,
            "employment_history": employment_history,
            "employment_history_rule_trace": income_rules_obj.get("trace"),
            "variable_income_todo": VARIABLE_INCOME_TODO,
            "data_path": {
                "meridian": "seeded entity_states.qualifying_monthly (PATH 1, unchanged)",
                "real_tenant": "income_sources via INC-A pipeline (PATH 2)",
            },
            "doc_fields_attached": False,
            "enricher_todo": (
                "Attach W2_CURRENT / PAYSTUB_CURRENT extracted_fields to the income "
                "bundle so qualify_from_w2_doc / qualify_from_paystub run on PATH 2."
            ),
        }

        # ── INC-E: retirement / SS / asset-depletion / investment (ADVISORY) ──
        # Catalogue-driven (RetirementIncomeResolver reads the income_rules
        # injected above). Asset depletion runs on REAL entity_states.
        # total_liquid_assets (attached by the enricher); SS/pension/investment
        # have no source docs yet → foundation only (advisory, no input → 0).
        # output_payload only; proposed_outcome + verified_income UNCHANGED.
        retire_resolver = RetirementIncomeResolver(rules=income_rule_values)
        total_liquid_assets = ev.get("total_liquid_assets")
        asset_depletion = retire_resolver.qualify_asset_depletion({
            "cash_savings": float(total_liquid_assets or 0),
            "retirement_assets": 0,
            "equity_assets": 0,
            "down_payment_used": 0,
            "closing_costs_used": 0,
        })
        retirement_income_analysis = {
            "resolver": "RetirementIncomeResolver",
            "scope": ("asset_depletion runs on real total_liquid_assets; "
                      "SS/pension/investment are foundation-only (no source docs)"),
            "asset_depletion": asset_depletion,
            "total_liquid_assets": total_liquid_assets,
            "rule_trace": income_rules_obj.get("trace"),
            "extraction_todo": (
                "SS/pension/IRA/dividend income need a separate extraction prompt "
                "(SSA_AWARD_LETTER, PENSION/1099-R, 1099-DIV/INT) before qualify_ss "
                "/ qualify_pension / qualify_dividends_interest run on live data."
            ),
        }

        # ── INC-F: alimony / child support (ADVISORY, foundation) ──────────
        # Catalogue-driven (AlimonyChildSupportResolver reads income_rules).
        # Input shape = the DIVORCE_DECREE Vision extractor fields; meridian has
        # no decree docs, so every method returns not_applicable (correct — this
        # is a foundation pass). output_payload only; proposed_outcome untouched.
        # Live data flows on PATH 2 (ingest_document -> income_sources).
        alimony_resolver = AlimonyChildSupportResolver(rules=income_rule_values)
        decree = latest_object(bundle, "DivorceDecree") or {}
        alimony_child_support_analysis = {
            "resolver": "AlimonyChildSupportResolver",
            "scope": "received (3yr continuance) + paid (DTI treatment); foundation only",
            "alimony_received": alimony_resolver.qualify_alimony_received(decree),
            "child_support_received": alimony_resolver.qualify_child_support_received(decree),
            "alimony_paid": alimony_resolver.treat_alimony_paid(decree),
            "child_support_paid": alimony_resolver.treat_child_support_paid(decree),
            "rule_trace": income_rules_obj.get("trace"),
            "decree_present": bool(decree),
            "extraction_todo": (
                "DIVORCE_DECREE docs (Vision extractor RA-EX-D emits alimony_monthly/"
                "receiving/termination_date + child_support_monthly/paying) must be "
                "ingested + populated to income_sources/obligations for PATH 2."
            ),
        }

        return OfflineReasoning(
            output_payload={
                "verified_income": verified,
                "income_confidence_score": round(confidence_score, 3),
                "employment_type": employment_type,
                # INC-B — advisory W2 base-income analysis (additive).
                "income_analysis": income_analysis,
                # INC-E — advisory retirement/SS/asset-depletion/investment (additive).
                "retirement_income_analysis": retirement_income_analysis,
                # INC-F — advisory alimony/child-support (additive).
                "alimony_child_support_analysis": alimony_child_support_analysis,
                # RULE 5 — evidence resolution visible to auditors.
                "income_source": income_source,
                "income_method": income_method,
                "evidence_income_confidence": evidence_income_confidence,
                "evidence_qualifying_monthly": (
                    float(ev_income_value) if ev_income_value else None
                ),
                "evidence_populated": evidence_populated,
                # Catalogue threshold provenance (federal/agency/overlay/applied).
                "threshold_trace": threshold_trace,
                "payroll_verified": reconciled_attempts > 0,
                "income_discrepancy_pct": round(discrepancy, 3),
                "multiple_income_sources": multiple_sources,
                "foreign_income": foreign_income,
                # Pass-through from the upstream so downstream
                # consumers don't have to re-fetch the trace.
                "reconciliation_status": reconciliation_status,
                "reconciled_employer_count": len(reconciled_employers),
                "comp_drift_pct": round(comp_drift_pct, 3),
                "manual_voe_required": manual_voe_required,
                "gap_letter_required": gap_letter_required,
                "tax_transcript_required": tax_transcript_required,
            },
            proposed_outcome=outcome,
            confidence=round(confidence_score, 3),
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Income is reliable when the upstream reconciliation "
                "produces auto_verified or partial-without-conflict, "
                "stated-vs-verified discrepancy is below 25%, and "
                "employment is single-source non-foreign salaried."
            ),
            conclusion=(
                f"reconciliation_status={reconciliation_status} on "
                f"{reconciled_attempts} attempt(s) across "
                f"{len(reconciled_employers)} employer(s); "
                f"verified ${verified:,.0f} vs stated ${stated:,.0f} "
                f"(discrepancy {discrepancy:.0%}); "
                f"confidence {confidence_score:.2f} → {outcome.value}"
            ),
            confidence_basis=(
                "Confidence is anchored to the upstream reconciliation "
                "verdict: 0.95 for auto_verified, 0.85 partial, 0.55 "
                "conflict, 0.4 missing — penalised by stated/verified "
                "drift, provider conflict, and non-salaried employment."
            ),
            summary=(
                f"Verified income ${verified:,.0f} (reconciled "
                f"{reconciliation_status}); proposed {outcome.value}."
            ),
        )


__all__ = ["IncomeVerificationAgent"]
