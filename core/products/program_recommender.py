"""EX2-B — program recommendation engine.

Given a borrower profile (score / DTI / LTV / loan amount / income), evaluates a
product matrix and returns the programs they qualify for now PLUS the programs they
ALMOST qualify for, each with an actionable, quantified gap (raise score N points /
reduce debt $X / put $Y more down). Sync + DB-less (RULE 5/6); RULE 11 (data_source
+ missing_inputs on every product result); ranked (eligible first, then closest gap).

It does NOT re-run the 14 personas — it's a pure function on the profile + matrix.
It evaluates ACROSS programs (the point of a recommender): the submitted loan_type
is reported as context but does NOT exclude products; only genuine program gates
apply (VA requires veteran status). A NULL gate input (e.g. SC03's dti_back) ->
not_applicable + missing_inputs, never a confident eligibility.

PRODUCT_MATRIX is a v1 own-copy of the cited agency floors (mirrors the inline
catalog in product_eligibility; overlays may TIGHTEN via _effective_threshold).
FOLLOW-UP: unify this and the persona's _PRODUCTS into one shared, catalogue-sourced
matrix once a green 16/16 can confirm the persona refactor.
"""
from __future__ import annotations

from typing import Optional

PRODUCT_MATRIX = [
    {"product_id": "CONV_CONFORMING", "name": "Conventional Conforming",
     "min_score": 620, "max_dti": 45.0, "max_ltv": 97.0, "requires_mi_above_ltv": 80.0,
     "max_loan": 806500, "citation": "Fannie B2-1.2-01 + B3-5.1-01 + B3-6-02"},
    {"product_id": "CONV_HOMEREADY", "name": "HomeReady (Fannie)",
     "min_score": 620, "max_dti": 45.0, "max_ltv": 97.0, "requires_mi_above_ltv": 80.0,
     "max_loan": 806500, "adu_income_allowed": True, "citation": "Fannie HomeReady B5-6-01"},
    {"product_id": "FHA_30", "name": "FHA 30-Year Fixed",
     "min_score": 580, "max_dti": 50.0, "max_ltv": 96.5, "max_loan": 498257,
     "mip_required": True, "citation": "FHA HUD 4000.1"},
    {"product_id": "VA_30", "name": "VA 30-Year Fixed",
     "min_score": 620, "max_dti": 41.0, "max_ltv": 100.0, "max_loan": 0,
     "veteran_only": True, "citation": "VA Pamphlet 26-7"},
    {"product_id": "CONV_HIGH_BALANCE", "name": "Conventional High Balance",
     "min_score": 680, "max_dti": 45.0, "max_ltv": 90.0, "max_loan": 1500000,
     "citation": "Fannie B2-1.1-01 (high-balance)"},
    {"product_id": "JUMBO", "name": "Jumbo / Non-Conforming",
     "min_score": 720, "max_dti": 43.0, "max_ltv": 80.0, "max_loan": 5000000,
     "citation": "Lender portfolio guidelines"},
]

NEAR_MISS_SCORE_PTS = 40
NEAR_MISS_DTI_PCT = 10
NEAR_MISS_LTV_PCT = 15


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


class ProgramRecommender:
    def __init__(self, overlay_rules: Optional[dict] = None):
        self._overlay = overlay_rules or {}

    def _effective_threshold(self, product: dict, key: str) -> float:
        """Overlay may tighten an agency default (e.g. <product>_min_score)."""
        ov = self._overlay.get(f"{product['product_id'].lower()}_{key}")
        return _f(ov if ov is not None else product.get(key, 0))

    def evaluate_product(self, profile: dict, product: dict) -> dict:
        pid, name = product["product_id"], product["name"]
        score, dti, ltv = profile.get("mid_credit_score"), profile.get("dti_back"), profile.get("ltv")
        loan_amount = _f(profile.get("loan_amount"))
        is_veteran = bool(profile.get("is_veteran", False))

        missing = []
        if score is None:
            missing.append("mid_credit_score not in entity_states")
        if dti is None:
            missing.append("dti_back not in entity_states")
        if ltv is None:
            missing.append("ltv not in entity_states")
        if missing:
            return {"product_id": pid, "name": name, "eligible": False,
                    "status": "not_applicable", "gaps": [], "near_miss_score": 0.0,
                    "data_source": "entity_states", "missing_inputs": missing,
                    "citation": product["citation"]}

        if product.get("veteran_only") and not is_veteran:
            return {"product_id": pid, "name": name, "eligible": False,
                    "status": "ineligible", "reason": "veteran_status_required", "gaps": [],
                    "near_miss_score": 0.0, "citation": product["citation"],
                    "data_source": "entity_states.borrower.is_veteran", "missing_inputs": []}

        score, dti, ltv = _f(score), _f(dti), _f(ltv)
        min_score = self._effective_threshold(product, "min_score")
        max_dti = self._effective_threshold(product, "max_dti")
        max_ltv = self._effective_threshold(product, "max_ltv")
        max_loan = _f(product.get("max_loan"))
        gaps: list = []

        if score < min_score:
            gaps.append({"dimension": "credit_score", "current": score, "required": min_score,
                         "gap": round(min_score - score, 0),
                         "action": f"Raise credit score by {min_score - score:.0f} points",
                         "citation": product["citation"]})

        if max_dti and dti > max_dti:
            income = _f(profile.get("qualifying_monthly"), 1) or 1
            piti = _f(profile.get("piti_monthly"))
            oblig = _f(profile.get("monthly_obligations"))
            current_total = oblig + piti
            max_allowed = income * (max_dti / 100.0)
            debt_reduction = max(0.0, current_total - max_allowed)
            income_increase = max(0.0, (current_total / (max_dti / 100.0)) - income) if max_dti else 0.0
            gaps.append({"dimension": "dti", "current": round(dti, 1), "required_max": max_dti,
                         "excess_pct": round(dti - max_dti, 1),
                         "debt_reduction_needed": round(debt_reduction, 0),
                         "income_increase_needed": round(income_increase, 0),
                         "action": (f"Reduce monthly debt by ${debt_reduction:,.0f} or raise "
                                    f"income by ${income_increase:,.0f}/mo"),
                         "citation": product["citation"]})

        if max_ltv and ltv > max_ltv:
            purchase_price = loan_amount / (ltv / 100.0) if ltv else 0.0
            current_down = purchase_price - loan_amount
            target_loan = purchase_price * (max_ltv / 100.0)
            down_needed = max(0.0, purchase_price - target_loan - current_down)
            gaps.append({"dimension": "ltv", "current": round(ltv, 1), "required_max": max_ltv,
                         "additional_down": round(down_needed, 0),
                         "action": f"Additional ${down_needed:,.0f} down payment required",
                         "citation": product["citation"]})

        if max_loan and loan_amount > max_loan:
            gaps.append({"dimension": "loan_amount", "current": loan_amount, "max_allowed": max_loan,
                         "excess": round(loan_amount - max_loan, 0),
                         "action": f"Loan ${loan_amount:,.0f} exceeds limit ${max_loan:,.0f}",
                         "citation": product["citation"]})

        eligible = not gaps
        near_miss_score = 0.0
        if not eligible:
            for g in gaps:
                if g["dimension"] == "credit_score" and g["gap"] <= NEAR_MISS_SCORE_PTS:
                    near_miss_score += (NEAR_MISS_SCORE_PTS - g["gap"]) / NEAR_MISS_SCORE_PTS
                elif g["dimension"] == "dti" and g["excess_pct"] <= NEAR_MISS_DTI_PCT:
                    near_miss_score += (NEAR_MISS_DTI_PCT - g["excess_pct"]) / NEAR_MISS_DTI_PCT
                elif g["dimension"] == "ltv" and g["additional_down"] <= loan_amount * (NEAR_MISS_LTV_PCT / 100.0):
                    near_miss_score += 0.5

        return {
            "product_id": pid, "name": name, "eligible": eligible,
            "status": "eligible" if eligible else ("near_miss" if near_miss_score > 0 else "ineligible"),
            "gaps": gaps, "gap_count": len(gaps), "near_miss_score": round(near_miss_score, 3),
            "est_payment": _f(profile.get("piti_monthly")) if eligible and profile.get("piti_monthly") else None,
            "requires_mi": bool(product.get("requires_mi_above_ltv")
                                and ltv > _f(product.get("requires_mi_above_ltv"), 999)),
            "citation": product["citation"],
            "data_source": "entity_states (score/dti/ltv/loan_amount)", "missing_inputs": []}

    def recommend(self, profile: dict) -> dict:
        results = [self.evaluate_product(profile, p) for p in PRODUCT_MATRIX]
        eligible = [r for r in results if r["eligible"]]
        near_miss = sorted([r for r in results if r["status"] == "near_miss"],
                           key=lambda x: x["near_miss_score"], reverse=True)
        ineligible = [r for r in results if r["status"] == "ineligible"]
        not_applicable = [r for r in results if r["status"] == "not_applicable"]

        parts = []
        if profile.get("qualifying_monthly"):
            parts.append(f"income ${_f(profile['qualifying_monthly']):,.0f}/mo")
        if profile.get("mid_credit_score") is not None:
            parts.append(f"score {profile['mid_credit_score']}")
        if profile.get("dti_back") is not None:
            parts.append(f"DTI {_f(profile['dti_back']):.0f}%")
        if profile.get("ltv") is not None:
            parts.append(f"LTV {_f(profile['ltv']):.0f}%")

        return {
            "profile_summary": " | ".join(parts),
            "submitted_loan_type": profile.get("loan_type"),
            "eligible_products": eligible,
            "near_miss_products": near_miss[:3],
            "ineligible_products": ineligible,
            "not_applicable": not_applicable,
            "eligible_count": len(eligible), "near_miss_count": len(near_miss),
            "top_recommendation": eligible[0] if eligible else (near_miss[0] if near_miss else None),
            "data_source": "entity_states + PRODUCT_MATRIX",
            "missing_inputs": sorted({m for r in results for m in r.get("missing_inputs", [])}),
            "citation": "Fannie B2-1.2-01 + B3-5.1-01 + FHA HUD 4000.1 + VA Pamphlet 26-7"}


__all__ = ["ProgramRecommender", "PRODUCT_MATRIX",
           "NEAR_MISS_SCORE_PTS", "NEAR_MISS_DTI_PCT", "NEAR_MISS_LTV_PCT"]
