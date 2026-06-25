"""SC-B — the 16 meridian scenarios as a typed library (read-only data).

Single source of truth that consolidates what previously lived as two loose dicts
in scripts/evaluate_meridian_scenarios.py (EXPECTED_OUTCOMES + SCENARIO_NOTES) plus
the numeric inputs in entity_states. All values are REAL (pulled from the live
meridian fixtures) — no placeholders.

expected_key_decision / expected_outcome are the live EXPECTED_OUTCOMES pairs (the
per-persona decision the 16/16 eval verifies). underwriting_outcome is the overall
loan outcome (the underwriting_decision aggregate); the two legitimately differ
(e.g. SC16 closing_readiness=escalate but the loan overall = recommend).

`conditions` are computed from each loan's real value vs the meridian overlay
thresholds below — factual breaches only, never fabricated (a value within its
threshold yields no condition). The overlay constants are inlined here as fixture
data (acceptable for a meridian fixture library per SC-B scope — NOT production
rule code; production reads them from the catalogue via rule_loader/ThresholdResolver).
"""
from __future__ import annotations

from core.scenarios.base import Scenario, ScenarioCondition

# Meridian conventional overlays (verified live: overlay_rules credit_floor=660,
# dti_back_max=43, ltv_max_purchase=95).
CREDIT_FLOOR = 660
DTI_MAX = 43.0
LTV_MAX = 95.0


def _credit_condition(score):
    if score is not None and score < CREDIT_FLOOR:
        return ScenarioCondition(
            rule_name="min_credit_score", borrower_value=score,
            threshold_value=CREDIT_FLOOR, breach=round(CREDIT_FLOOR - score, 1),
            direction="below", citation="Fannie B3-5.1-01", layer="overlay")
    return None


def _dti_condition(dti):
    if dti is not None and dti > DTI_MAX:
        return ScenarioCondition(
            rule_name="dti_back_max", borrower_value=dti, threshold_value=DTI_MAX,
            breach=round(dti - DTI_MAX, 2), direction="above",
            citation="Fannie B3-6-02", layer="overlay")
    return None


def _ltv_condition(ltv):
    if ltv is not None and ltv > LTV_MAX:
        return ScenarioCondition(
            rule_name="ltv_max_purchase", borrower_value=ltv, threshold_value=LTV_MAX,
            breach=round(ltv - LTV_MAX, 2), direction="above",
            citation="Fannie B2-1.2-01", layer="overlay")
    return None


def _notify(uw_outcome, conditions):
    """Derived routing hint (NOT stored data): a credit floor breached below the
    620 agency floor needs the senior credit officer; other declines a UW manager;
    escalations a UW; clean approvals nobody."""
    if uw_outcome == "recommend":
        return None
    if any(c.rule_name == "min_credit_score" and c.borrower_value < 620 for c in conditions):
        return "senior_credit_officer"
    if uw_outcome == "escalate":
        return "uw"
    return "uw_manager"


# sc, title, intent, key_decision, key_outcome, uw_aggregate,
# score, ltv, dti, loan, qual_monthly, piti_monthly, liquid, oblig, explanation
_ROWS = [
    ("SC01", "High DTI + Fraud Flags",
     "fraud_screening — straw-buyer pattern; DTI 55.98%",
     "fraud_screening", "block", "block",
     720, 91.84, 55.98, 382500, 8000.0, 2678.50, 24500.0, 1800.0,
     "Fraud screening blocks on straw-buyer signals; DTI 55.98% also exceeds the 43% overlay."),
    ("SC02", "High DTI Conventional",
     "dti_calculation — DTI 80.21% extreme",
     "dti_calculation", "block", "block",
     742, 91.84, 80.21, 468000, 9000.0, 3277.23, 91000.0, 3942.0,
     "DTI 80.21% far exceeds the 43% overlay cap."),
    ("SC03", "NULL DTI — Data Gap",
     "income_verification — DTI null, income not fully verified",
     "income_verification", "recommend", "block",
     718, 81.63, None, 492000, 9937.5, 3232.09, 52000.0, 3450.0,
     "DTI is NULL — income not fully verified; income_verification recommends pending documentation."),
    ("SC04", "Employment Gap + High DTI",
     "employment_reconciliation — gap escalation; DTI 57.59%",
     "employment_reconciliation", "escalate", "block",
     698, 81.63, 57.59, 308000, 7333.33, 2023.34, 34500.0, 2200.0,
     "Employment gap escalates for manual reconciliation; DTI 57.59% also exceeds overlay."),
    ("SC05", "Compliance + High DTI",
     "compliance_check — ATR concern; DTI 59.18%",
     "compliance_check", "block", "block",
     768, 86.73, 59.18, 578000, 12083.33, 3951.18, 67000.0, 3200.0,
     "Compliance flags ATR risk; DTI 59.18% exceeds overlay."),
    ("SC06", "First-Time Buyer Credit + DTI",
     "credit_assessment — score 627; FTB waiver narrative",
     "credit_assessment", "recommend", "block",
     627, 95.00, 64.37, 308750, 6500.0, 2234.10, 43000.0, 1950.0,
     "Credit 627 flagged for review. FTB waiver lowers the block threshold to 620 "
     "but allow still requires credit >= 680. UW reviews and approves with waiver documented."),
    ("SC07", "Borderline DTI — Rate Locked",
     "dti_calculation — DTI 41.99% borderline; rate-lock rain check",
     "dti_calculation", "recommend", "escalate",
     712, 91.84, 41.99, 400500, 8500.0, 2804.55, 41000.0, 765.0,
     "DTI 44% flagged for review under current rules. Rain check badge shows the loan "
     "is rate-locked. UW confirms DTI was within v1 cap at lock date. Override documented "
     "with rain check reasoning."),
    ("SC08", "Total Multi-Block Decline",
     "credit_assessment — score 578 below floor; DTI 83.11%",
     "credit_assessment", "block", "block",
     578, 91.84, 83.11, 535500, 11250.0, 3749.90, 0.0, 5600.0,
     "Score 578 below the 620 agency floor and the 660 overlay; DTI 83.11%. "
     "Best multi-block demo (credit + DTI both fail)."),
    ("SC09", "Income Verification Escalation",
     "income_verification — income gap escalate; DTI 61.48%",
     "income_verification", "escalate", "block",
     705, 91.84, 61.48, 441000, 9333.33, 3088.16, 31000.0, 2650.0,
     "Income verification incomplete -> escalate; DTI 61.48% exceeds overlay."),
    ("SC10", "Closing Readiness + DTI",
     "closing_readiness — missing docs; DTI 56.75%",
     "closing_readiness", "block", "block",
     734, 81.63, 56.75, 408000, 9833.33, 2680.27, 59000.0, 2900.0,
     "Closing docs incomplete -> block; DTI 56.75% exceeds overlay."),
    ("SC11", "High DTI Conventional",
     "dti_calculation — DTI 72.87%",
     "dti_calculation", "block", "block",
     722, 81.63, 72.87, 364000, 8500.0, 2391.22, 36000.0, 3803.0,
     "DTI 72.87% far exceeds the 43% overlay."),
    ("SC12", "Rental Income Resolution",
     "income_verification — rental income resolved; DTI 88.15%",
     "income_verification", "recommend", "block",
     708, 91.84, 88.15, 355500, 7850.0, 2489.43, 30500.0, 2976.0,
     "Rental income resolved from Schedule E (gross $24,000 - expenses $8,400 + "
     "depreciation $4,200 = $19,800/yr = $1,650/mo, Fannie Mae B3-3.1-08). Income is "
     "verifiable -> income_verification recommends."),
    ("SC13", "Product Ineligibility",
     "product_eligibility — product-type block; DTI 58.36%",
     "product_eligibility", "block", "block",
     751, 91.84, 58.36, 310500, 7666.67, 2174.31, 44500.0, 2300.0,
     "Product eligibility block; DTI 58.36% also exceeds overlay."),
    ("SC14", "Borderline DTI Escalate",
     "product_eligibility — DTI 42.0% borderline escalate",
     "product_eligibility", "escalate", "escalate",
     724, 91.84, 42.00, 378000, 7333.33, 2646.99, 0.0, 433.0,
     "DTI 42% within overlay (43%); product escalates for manual review."),
    ("SC15", "Asset Verification Escalation",
     "asset_verification — undocumented deposit; DTI 60.71%",
     "asset_verification", "escalate", "block",
     715, 86.73, 60.71, 314500, 7000.0, 2149.91, 42000.0, 2100.0,
     "Asset verification flags an undocumented deposit -> escalate; DTI 60.71% exceeds overlay."),
    ("SC16", "Clean Approval",
     "closing_readiness — escalate; loan overall recommend, thresholds met",
     "closing_readiness", "escalate", "recommend",
     729, 86.73, 42.00, 374000, 8000.0, 2556.65, 0.0, 803.0,
     "Clean loan — score 729, LTV 86.7%, DTI 42% all within thresholds; the loan overall "
     "is a recommend (closing_readiness escalates on a documentation step)."),
]


def _build(row) -> Scenario:
    (sc, title, intent, key_dec, key_out, uw_agg, score, ltv, dti, loan,
     qual, piti, liquid, oblig, explanation) = row
    conditions = [c for c in (_credit_condition(score), _dti_condition(dti),
                              _ltv_condition(ltv)) if c]
    missing = []
    if dti is None:
        missing.append("dti_back is NULL in entity_states — income not fully verified; "
                        "DTI gate not evaluated (RULE 11)")
    return Scenario(
        scenario_id=sc, application_id=f"APP-MRID-{sc}", tenant_id="meridian",
        title=title, intent=intent,
        expected_key_decision=key_dec, expected_outcome=key_out,
        underwriting_outcome=uw_agg,
        mid_credit_score=score, ltv=ltv, dti_back=dti, loan_amount=loan,
        qualifying_monthly=qual, piti_monthly=piti, total_liquid_assets=liquid,
        monthly_obligations=oblig,
        conditions=conditions, notify_role=_notify(uw_agg, conditions),
        explanation=explanation, missing_inputs=missing)


MERIDIAN_SCENARIOS = [_build(r) for r in _ROWS]
MERIDIAN_BY_ID = {s.scenario_id: s for s in MERIDIAN_SCENARIOS}
MERIDIAN_BY_APP = {s.application_id: s for s in MERIDIAN_SCENARIOS}

# Span the outcome space + distinct block types for demos.
BEST_DEMO_SCENARIOS = ["SC16", "SC08", "SC06", "SC07", "SC01", "SC12"]

__all__ = [
    "MERIDIAN_SCENARIOS", "MERIDIAN_BY_ID", "MERIDIAN_BY_APP",
    "BEST_DEMO_SCENARIOS", "CREDIT_FLOOR", "DTI_MAX", "LTV_MAX",
]
