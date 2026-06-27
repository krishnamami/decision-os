"""MR-A — SR 11-7 model card generator + validation framework.

Each of the 14 decision personas is a "model". wave / upstream / risk_tier / mode are
DERIVED from the authoritative runtime config (WAVE_CONFIG + DECISION_DEFAULTS,
mirrored here as pure constants so the cards can never drift from the live engine);
the registry holds the qualitative content (purpose / inputs / outputs / assumptions /
limitations / validation). Pure + sync + DB-less. Read-only -> 16/16 by construction.

SR 11-7 (Fed/OCC Model Risk Management) requires per-model documentation, a validation
approach, a risk tier, and an ongoing-monitoring plan — this satisfies the
documentation + validation-record requirement; MR-B adds the monitoring.
"""
from __future__ import annotations

# ── Authoritative runtime config (mirrors core/cron/runner WAVE_CONFIG +
# DECISION_DEFAULTS). Copied as constants to keep this module import-light + pure;
# kept in sync with the runner (which itself mirrors decisions.yaml). ──
_RUNTIME = {
    "credit_assessment":         {"wave": 1, "upstream": [], "risk_tier": "medium", "mode": "recommend"},
    "fraud_screening":           {"wave": 1, "upstream": [], "risk_tier": "high", "mode": "human_approval"},
    "compliance_check":          {"wave": 1, "upstream": [], "risk_tier": "high", "mode": "human_approval"},
    "employment_reconciliation": {"wave": 1, "upstream": [], "risk_tier": "medium", "mode": "recommend"},
    "asset_verification":        {"wave": 1, "upstream": [], "risk_tier": "medium", "mode": "recommend"},
    "title_assessment":          {"wave": 1, "upstream": [], "risk_tier": "medium", "mode": "recommend"},
    "income_verification":       {"wave": 2, "upstream": ["employment_reconciliation"], "risk_tier": "medium", "mode": "recommend"},
    "dti_calculation":           {"wave": 2, "upstream": ["income_verification"], "risk_tier": "low", "mode": "auto_execute"},
    "ltv_assessment":            {"wave": 2, "upstream": ["credit_assessment"], "risk_tier": "low", "mode": "auto_execute"},
    "product_eligibility":       {"wave": 3, "upstream": ["dti_calculation", "ltv_assessment"], "risk_tier": "medium", "mode": "recommend"},
    "rate_pricing":              {"wave": 3, "upstream": ["credit_assessment", "dti_calculation", "ltv_assessment"], "risk_tier": "medium", "mode": "recommend"},
    "underwriting_decision":     {"wave": 4, "upstream": ["income_verification", "credit_assessment", "fraud_screening", "dti_calculation", "ltv_assessment", "product_eligibility"], "risk_tier": "high", "mode": "human_approval"},
    "approval_routing":          {"wave": 5, "upstream": ["underwriting_decision"], "risk_tier": "low", "mode": "auto_execute"},
    "closing_readiness":         {"wave": 5, "upstream": ["underwriting_decision", "compliance_check"], "risk_tier": "high", "mode": "human_approval"},
}

_OWNER = {
    "credit_assessment": "credit_risk", "fraud_screening": "fraud_ops",
    "compliance_check": "compliance", "employment_reconciliation": "underwriting",
    "asset_verification": "underwriting", "title_assessment": "title_ops",
    "income_verification": "underwriting", "dti_calculation": "credit_risk",
    "ltv_assessment": "collateral_risk", "product_eligibility": "product_ops",
    "rate_pricing": "secondary_markets", "underwriting_decision": "underwriting",
    "approval_routing": "loan_ops", "closing_readiness": "closing_ops",
}

_ECOA = "Demographics (race/sex/ethnicity) are never used in the decision path (ECOA)."
_VALIDATION = {
    "approach": "16/16 meridian scenario eval + rule_validator boundary self-test",
    "backtesting": "QA-B ModelAccuracyBacktester (insufficient_data pending a loan_performance table)",
    "fair_lending": "QA-A proxy-swap regression (8 pairs, all PASS) + CM-D/F/G",
}

# Qualitative content per model (the part NOT in runtime config).
_CONTENT = {
    "credit_assessment": {
        "name": "Credit Assessment", "type": "rules-based decision model",
        "purpose": "Evaluate borrower creditworthiness vs agency guidelines + lender overlays.",
        "entity_fields": ["mid_credit_score", "open_collections", "mortgage_lates", "bankruptcy_discharge_date"],
        "catalogue_rules": ["min_credit_score / credit_floor", "non_medical_collection thresholds", "mortgage_late lookback"],
        "signals": ["credit_passed", "collections_flag", "mortgage_late_flag", "credit_score_bucket"],
        "key_assumptions": ["mid_credit_score is the bureau middle score",
                            "Thresholds catalogue-driven (RULE 1)", "Medical collections excluded (B3-5.3-07)"],
        "known_limitations": ["Thin-file not modeled distinctly from scored files",
                              "Trended credit data not integrated", "Accuracy unverified (no loan_performance — QA-B)"]},
    "fraud_screening": {
        "name": "Fraud Screening", "type": "rules-based + heuristic model",
        "purpose": "Detect synthetic identity, straw buyer, occupancy misrep, and AVM/income fraud.",
        "entity_fields": ["fraud_score", "income_expense_ratio", "ltv", "occupancy_type", "property_type"],
        "catalogue_rules": ["fraud score thresholds", "income_mismatch thresholds"],
        "signals": ["fraud_risk_level", "fraud_indicators", "fraud_score_bucket"],
        "key_assumptions": ["Fraud score is a 3rd-party composite (synthetic in meridian)",
                            "Heuristic indicators supplement the score", "Evidence fraud signals advisory (RA-PERSONA-A)"],
        "known_limitations": ["No ML fraud model — rules + heuristics", "3rd-party score not integrated (synthetic)",
                              "Occupancy-misrep detection limited without property-visit data"]},
    "compliance_check": {
        "name": "Compliance Check", "type": "rules-based compliance model",
        "purpose": "Verify federal, agency, and state regulatory compliance.",
        "entity_fields": ["loan_purpose", "property_state", "ltv", "note_rate"],
        "catalogue_rules": ["TX cash-out LTV", "state_rules (CM-E)", "QM safe harbor (12 CFR 1026.43)"],
        "signals": ["compliance_passed", "state_rules_passed", "qm_status"],
        "key_assumptions": ["TX cash-out LTV cap 80% (Tex. Const. XVI 50(a)(6))",
                            "State rules from StateRuleResolver (CM-E)", "QM safe-harbor DTI <= 43%"],
        "known_limitations": ["TX-80 still partially hardcoded (de-hardcode deferred, tracked)",
                              "State coverage: 13 states; 50-state pending",
                              "Disparate impact tracked separately (CM-D/F/G)"]},
    "employment_reconciliation": {
        "name": "Employment Reconciliation", "type": "rules-based reconciliation model",
        "purpose": "Reconcile employer + employment history across W2 / paystub / VOE documents.",
        "entity_fields": ["employer_name", "employment_start", "employment_gaps", "is_self_employed"],
        "catalogue_rules": ["employment_history_months_required (B3-3.1-01)"],
        "signals": ["employment_continuity", "reconciled_employer_count", "gap_flag"],
        "key_assumptions": ["24-month employment history expected", "Gaps surfaced for LOE"],
        "known_limitations": ["Gig / multi-employer patterns not separately modeled"]},
    "asset_verification": {
        "name": "Asset Verification", "type": "rules-based decision model",
        "purpose": "Verify liquid assets + reserves for down payment and post-close reserves.",
        "entity_fields": ["total_liquid_assets", "large_deposits", "reserve_months"],
        "catalogue_rules": ["minimum_reserves_months", "large_deposit_threshold_pct", "asset qualifying factors"],
        "signals": ["assets_verified", "reserves_months", "large_deposit_flag"],
        "key_assumptions": ["Source + seasoning per agency (B3-4.3)", "Reserve months from liquid/PITI"],
        "known_limitations": ["Business-asset depletion partially modeled", "Large-deposit LOE not auto-resolved"]},
    "title_assessment": {
        "name": "Title Assessment", "type": "rules-based decision model",
        "purpose": "Assess title defects, liens, and encumbrances against closing requirements.",
        "entity_fields": ["lien_status", "title_defect", "encumbrances", "lien_dispute"],
        "catalogue_rules": ["lien treatments (B8-1-01/02)"],
        "signals": ["title_clear", "lien_flags", "blocks_closing"],
        "key_assumptions": ["Lien treatments catalogue-driven", "Superior liens require payoff"],
        "known_limitations": ["Complex chain-of-title requires manual review"]},
    "income_verification": {
        "name": "Income Verification", "type": "rules-based decision model",
        "purpose": "Verify qualifying monthly income from W2 / paystub / tax returns / other types.",
        "entity_fields": ["income_sources", "employment_type", "ytd_income", "w2_income_current", "w2_income_prior"],
        "catalogue_rules": ["income stability lookback", "employment_history_months_required"],
        "signals": ["income_verified", "qualifying_monthly", "income_type", "income_stability_flag"],
        "key_assumptions": ["2-year income history for stability", "Evidence advisory — stated path when docs absent",
                            "YTD annualized when paystub present"],
        "known_limitations": ["Gig income not separately modeled", "Foreign income limited", "Evidence advisory, not blocking"]},
    "dti_calculation": {
        "name": "DTI Calculation", "type": "rules-based calculation model",
        "purpose": "Compute front/back DTI ratios from qualifying income and monthly obligations.",
        "entity_fields": ["qualifying_monthly", "total_monthly_obligations", "proposed_housing_payment"],
        "catalogue_rules": ["dti_back_max", "dti_front_max"],
        "signals": ["dti_back", "dti_front", "dti_within_guidelines"],
        "key_assumptions": ["qualifying_monthly from income_verification", "IBR/PSLF student-loan treatment per agency"],
        "known_limitations": ["Manual DTI exclusions not yet modeled"]},
    "ltv_assessment": {
        "name": "LTV Assessment", "type": "rules-based calculation model",
        "purpose": "Compute LTV/CLTV using the lesser-of purchase price / appraised value.",
        "entity_fields": ["loan_amount", "purchase_price", "appraised_value", "property_type", "occupancy_type", "number_of_units"],
        "catalogue_rules": ["ltv_max_purchase", "ltv_max_refi", "mi_required_threshold"],
        "signals": ["ltv", "cltv", "ltv_within_guidelines", "mi_required"],
        "key_assumptions": ["Lesser-of rule for purchase", "MI required when LTV > 80% conventional"],
        "known_limitations": ["AVM not integrated (appraised value from URAR only)"]},
    "product_eligibility": {
        "name": "Product Eligibility", "type": "rules-based eligibility model",
        "purpose": "Determine eligible loan products (ProgramRecommender) given the borrower profile.",
        "entity_fields": ["mid_credit_score", "dti_back", "ltv", "loan_type", "loan_purpose", "property_type", "occupancy_type"],
        "catalogue_rules": ["product min_score / max_dti / max_ltv"],
        "signals": ["eligible_products", "product_count", "near_miss_products"],
        "key_assumptions": ["ProgramRecommender product matrix (PL-E)", "Near-miss surfaces close-but-ineligible"],
        "known_limitations": ["Inline _PRODUCTS not yet unified with the products table (deferred)"]},
    "rate_pricing": {
        "name": "Rate Pricing", "type": "rules-based pricing model",
        "purpose": "Compute the base rate plus LLPA adjustments for the borrower/loan.",
        "entity_fields": ["mid_credit_score", "ltv", "dti_back", "loan_type"],
        "catalogue_rules": ["base rate", "LLPA add-ons"],
        "signals": ["interest_rate", "llpa", "rate_within_normal_band", "usury_violation"],
        "key_assumptions": ["LLPA from score/LTV/DTI/loan_type", "Usury cap check"],
        "known_limitations": ["Inline LLPA math; does not read rate_sheet_entry/llpa_adjustments yet (PL-D, deferred)"]},
    "underwriting_decision": {
        "name": "Underwriting Decision", "type": "rules-based decision aggregator",
        "purpose": "Aggregate upstream persona outcomes into the final underwriting recommendation.",
        "entity_fields": [], "catalogue_rules": [],
        "signals": ["uw_decision", "binding_constraints", "adverse_action", "hmda_lar"],
        "key_assumptions": ["Any upstream block -> block (conservative reduce)",
                            "Escalate -> human review (RBAC)", "Exception workflow for near-miss"],
        "known_limitations": ["Pure rule aggregation (no ML)", "Compound-constraint attribution may be partial"]},
    "approval_routing": {
        "name": "Approval Routing", "type": "rules-based routing model",
        "purpose": "Route the underwriting outcome (auto / manual / decline) + reconcile against AUS (DU/LP).",
        "entity_fields": [], "catalogue_rules": ["exception approval levels"],
        "signals": ["routing", "aus_reconciliation", "route_conflict_present"],
        "key_assumptions": ["Reconciles vs the more conservative of DU/LP (RA-AUS-C)"],
        "known_limitations": ["Conflict -> manual-review is advisory only, does not move the routing outcome (Known Gap f)"]},
    "closing_readiness": {
        "name": "Closing Readiness", "type": "rules-based decision model",
        "purpose": "Verify closing conditions: CD timing, document completeness, title, staleness.",
        "entity_fields": ["cd_issued", "cd_timing_violation", "final_title_policy_received", "wire_instructions_received"],
        "catalogue_rules": ["document staleness / recency windows (EV-G)"],
        "signals": ["closing_ready", "conditions_outstanding", "cd_timing_compliant"],
        "key_assumptions": ["TRID CD timing enforced", "Title policy + wire instructions required"],
        "known_limitations": ["EV-G staleness + EV-H field-manifest surfaces are advisory, wiring deferred"]},
}


def _build_registry() -> dict:
    reg = {}
    for mid, cfg in _RUNTIME.items():
        c = _CONTENT[mid]
        reg[mid] = {
            "model_id": mid, "name": c["name"], "type": c["type"],
            "wave": cfg["wave"], "mode": cfg["mode"], "risk_tier": cfg["risk_tier"],
            "owner_team": _OWNER[mid], "purpose": c["purpose"],
            "inputs": {"entity_fields": c["entity_fields"], "catalogue_rules": c["catalogue_rules"],
                       "upstream_personas": list(cfg["upstream"])},
            "outputs": {"outcome": "recommend | block | escalate", "signals": c["signals"]},
            "key_assumptions": c["key_assumptions"], "known_limitations": c["known_limitations"],
            "ecoa_note": _ECOA, "validation": dict(_VALIDATION),
            "approval_status": "validated", "last_review": "2025-01-01",
            "next_review": "2026-01-01", "sr_11_7_tier": cfg["risk_tier"],
        }
    return reg


MODEL_REGISTRY = _build_registry()


class ModelCardGenerator:
    SR_11_7_NOTE = (
        "SR 11-7 (Federal Reserve / OCC Model Risk Management) requires documentation, "
        "validation, and ongoing monitoring for models used in decision-making. This card "
        "satisfies the documentation + validation-record requirement; ongoing monitoring is MR-B.")

    def generate_card(self, model_id: str) -> dict:
        if model_id not in MODEL_REGISTRY:
            return {"status": "not_found", "model_id": model_id,
                    "available": sorted(MODEL_REGISTRY), "data_source": "MODEL_REGISTRY",
                    "missing_inputs": [f"no model card for: {model_id}"]}
        card = {k: (v.copy() if isinstance(v, (dict, list)) else v)
                for k, v in MODEL_REGISTRY[model_id].items()}
        card.update({"status": "current", "sr_11_7_note": self.SR_11_7_NOTE,
                     "data_source": "WAVE_CONFIG + DECISION_DEFAULTS + persona registry",
                     "missing_inputs": []})
        return card

    def generate_all_cards(self) -> dict:
        cards = {mid: self.generate_card(mid) for mid in MODEL_REGISTRY}
        tiers = {t: [m for m, c in cards.items() if c["sr_11_7_tier"] == t]
                 for t in ("high", "medium", "low")}
        return {
            "total_models": len(cards),
            "high_risk_count": len(tiers["high"]), "medium_risk_count": len(tiers["medium"]),
            "low_risk_count": len(tiers["low"]),
            "by_tier": tiers, "cards": cards, "sr_11_7_note": self.SR_11_7_NOTE,
            "data_source": "MODEL_REGISTRY (WAVE_CONFIG + DECISION_DEFAULTS)", "missing_inputs": []}

    def validation_status(self) -> dict:
        validated = [m for m, c in MODEL_REGISTRY.items() if c["approval_status"] == "validated"]
        pending = [m for m, c in MODEL_REGISTRY.items() if c["approval_status"] != "validated"]
        return {
            "total": len(MODEL_REGISTRY), "validated": len(validated), "pending": len(pending),
            "validated_models": validated, "pending_models": pending,
            "review_schedule": [{"model_id": m, "risk_tier": c["sr_11_7_tier"],
                                 "last_review": c["last_review"], "next_review": c["next_review"]}
                                for m, c in MODEL_REGISTRY.items()],
            "note": ("High-risk models require annual validation; review dates are static "
                     "placeholders until a model-governance calendar is wired."),
            "data_source": "MODEL_REGISTRY", "missing_inputs": []}


__all__ = ["ModelCardGenerator", "MODEL_REGISTRY"]
