"""Compensating-factors detection engine (EX-B).

Detects the Fannie B3-2-02 compensating factors from the borrower's data and
scores them, so the EX-A ExceptionEngine can be fed REAL factors (not an empty
list). SYNC + DB-LESS (RULES 5/6); thresholds from the injected ``rules`` dict
(catalogue) with rule_loader.SAFE_DEFAULTS as the only fallback (RULE 9). Returns
findings in memory; never writes the DB (EX-C writes the compensating_factors
table). RULE 11: every detect_* method returns `data_source` + `missing_inputs`.

6 factors compute from existing entity_states fields (reserves, low_ltv,
excellent_credit, long_employment, limited_debt, large_down_payment); 2 lack
inputs (payment_shock, high_residual_income) → not_applicable + missing_inputs.
"""
from __future__ import annotations

from typing import Optional

_CITE = "Fannie B3-2-02"

# Loaded under the shared exception_rules bundle key (EXCEPTION_RULE_KEYS extended
# in exception_engine.py). Kept here for standalone use / documentation.
COMPENSATING_FACTOR_RULE_KEYS = [
    "substantial_reserves_months",
    "exceptional_reserves_months",
    "low_ltv_factor_max_pct",
    "excellent_credit_delta_pts",
    "long_employment_months",
    "minimal_debt_obligations_max_pct",
    "minimum_reserves_months",   # already seeded — baseline floor
]


async def load_compensating_factor_rules(conn, tenant_id: str,
                                         agency: str = "fannie") -> dict:
    from core.catalogue.rule_loader import get_rule
    values, trace = {}, {}
    for key in COMPENSATING_FACTOR_RULE_KEYS:
        r = await get_rule(conn, key, tenant_id, agency=agency)
        values[key] = r.get("applied")
        trace[key] = {"applied": r.get("applied"), "governed_by": r.get("governed_by")}
    return {"values": values, "trace": trace}


_STRENGTH_SCORE = {"strong": 3, "moderate": 2, "weak": 1, None: 0}


class CompensatingFactorsEngine:
    def __init__(self, rules: Optional[dict] = None):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._substantial_reserves = float(r.get("substantial_reserves_months", 6))
        self._exceptional_reserves = float(r.get("exceptional_reserves_months", 12))
        self._low_ltv_max = float(r.get("low_ltv_factor_max_pct", 75))
        self._excellent_credit_delta = float(r.get("excellent_credit_delta_pts", 60))
        self._long_employment_months = float(r.get("long_employment_months", 60))
        self._minimal_debt_pct = float(r.get("minimal_debt_obligations_max_pct", 10))
        self._baseline_reserves = float(r.get("minimum_reserves_months", 2))

    def detect_reserves(self, inputs: dict) -> dict:
        inputs = inputs or {}
        total_liquid = float(inputs.get("total_liquid_assets", 0) or 0)
        piti = float(inputs.get("piti_monthly", 0) or 0)
        if not piti:
            return {"factor_type": "substantial_reserves", "present": False,
                    "strength": None, "method": "reserves_piti_zero", "citation": _CITE,
                    "data_source": "entity_states.total_liquid_assets + piti_monthly",
                    "missing_inputs": ["piti_monthly is zero — cannot compute reserves months"]}
        reserves_months = round(total_liquid / piti, 1)
        if reserves_months >= self._exceptional_reserves:
            strength = "strong"
        elif reserves_months >= self._substantial_reserves:
            strength = "moderate"
        elif reserves_months >= self._baseline_reserves:
            strength = "weak"
        else:
            strength = None
        return {"factor_type": "substantial_reserves", "present": strength is not None,
                "strength": strength, "reserves_months": reserves_months,
                "exceptional_threshold": self._exceptional_reserves,
                "substantial_threshold": self._substantial_reserves,
                "method": f"{total_liquid} / {piti} = {reserves_months}mo", "citation": _CITE,
                "data_source": "entity_states.total_liquid_assets + entity_states.piti_monthly",
                "missing_inputs": []}

    def detect_low_ltv(self, inputs: dict) -> dict:
        inputs = inputs or {}
        ltv = float(inputs.get("ltv", 0) or 0)
        if not ltv:
            return {"factor_type": "low_ltv", "present": False, "strength": None,
                    "method": "low_ltv_no_data", "citation": _CITE,
                    "data_source": "entity_states.ltv", "missing_inputs": ["ltv not available"]}
        strong_threshold = self._low_ltv_max
        moderate_threshold = self._low_ltv_max + 5
        if ltv <= strong_threshold:
            strength = "strong"
        elif ltv <= moderate_threshold:
            strength = "moderate"
        else:
            strength = None
        return {"factor_type": "low_ltv", "present": strength is not None, "strength": strength,
                "ltv": ltv, "strong_threshold": strong_threshold,
                "moderate_threshold": moderate_threshold,
                "method": f"LTV {ltv}% vs thresholds {strong_threshold}/{moderate_threshold}%",
                "citation": _CITE, "data_source": "entity_states.ltv", "missing_inputs": []}

    def detect_excellent_credit(self, inputs: dict) -> dict:
        inputs = inputs or {}
        score = float(inputs.get("mid_credit_score", 0) or 0)
        min_score = float(inputs.get("min_credit_score_applied", 620) or 620)
        if not score:
            return {"factor_type": "excellent_credit", "present": False, "strength": None,
                    "method": "credit_no_score", "citation": _CITE,
                    "data_source": "entity_states.mid_credit_score",
                    "missing_inputs": ["mid_credit_score not available"]}
        delta = score - min_score
        if delta >= self._excellent_credit_delta:
            strength = "strong"
        elif delta >= self._excellent_credit_delta / 2:
            strength = "moderate"
        else:
            strength = None
        return {"factor_type": "excellent_credit", "present": strength is not None,
                "strength": strength, "score": score, "min_score": min_score,
                "delta": round(delta, 0), "threshold": self._excellent_credit_delta,
                "method": f"score {score} - min {min_score} = delta {delta}", "citation": _CITE,
                "data_source": "entity_states.mid_credit_score", "missing_inputs": []}

    def detect_long_employment(self, inputs: dict) -> dict:
        from datetime import date, datetime
        inputs = inputs or {}
        period_start = inputs.get("employment_period_start")
        if not period_start:
            return {"factor_type": "long_employment", "present": False, "strength": None,
                    "method": "employment_no_start_date", "citation": _CITE,
                    "data_source": "entity_states.borrower.employment.period_start",
                    "missing_inputs": ["employment period_start not in bundle"]}
        if isinstance(period_start, str):
            try:
                period_start = datetime.fromisoformat(period_start).date()
            except ValueError:
                period_start = None
        elif isinstance(period_start, datetime):
            period_start = period_start.date()
        if not period_start:
            return {"factor_type": "long_employment", "present": False, "strength": None,
                    "method": "employment_invalid_date", "citation": _CITE,
                    "data_source": "entity_states.borrower.employment.period_start",
                    "missing_inputs": ["employment period_start invalid format"]}
        today = date.today()
        months = (today.year - period_start.year) * 12 + (today.month - period_start.month)
        if months >= self._long_employment_months:
            strength = "strong"
        elif months >= self._long_employment_months * 0.6:
            strength = "moderate"
        else:
            strength = None
        return {"factor_type": "long_employment", "present": strength is not None,
                "strength": strength, "tenure_months": months,
                "threshold": self._long_employment_months,
                "method": f"{months}mo employment vs {self._long_employment_months}mo threshold",
                "citation": _CITE,
                "data_source": "entity_states.borrower.employment.period_start",
                "missing_inputs": []}

    def detect_limited_debt(self, inputs: dict) -> dict:
        inputs = inputs or {}
        obligations = float(inputs.get("monthly_obligations", 0) or 0)
        income = float(inputs.get("qualifying_monthly", 0) or 0)
        if not income:
            return {"factor_type": "limited_debt", "present": False, "strength": None,
                    "method": "limited_debt_no_income", "citation": _CITE,
                    "data_source": "entity_states.monthly_obligations + qualifying_monthly",
                    "missing_inputs": ["qualifying_monthly is zero — cannot compute debt ratio"]}
        debt_pct = round(obligations / income * 100, 1)
        if debt_pct <= self._minimal_debt_pct:
            strength = "strong"
        elif debt_pct <= self._minimal_debt_pct * 2:
            strength = "moderate"
        else:
            strength = None
        return {"factor_type": "limited_debt", "present": strength is not None,
                "strength": strength, "debt_pct": debt_pct, "threshold": self._minimal_debt_pct,
                "method": f"{obligations}/{income}*100 = {debt_pct}%", "citation": _CITE,
                "data_source": "entity_states.monthly_obligations + entity_states.qualifying_monthly",
                "missing_inputs": []}

    def detect_large_down_payment(self, inputs: dict) -> dict:
        inputs = inputs or {}
        ltv = float(inputs.get("ltv", 0) or 0)
        if not ltv:
            return {"factor_type": "large_down_payment", "present": False, "strength": None,
                    "method": "down_payment_no_ltv", "citation": _CITE,
                    "data_source": "entity_states.ltv", "missing_inputs": ["ltv not available"]}
        down_pct = round(100 - ltv, 1)
        if down_pct >= 20:
            strength = "strong"
        elif down_pct >= 10:
            strength = "moderate"
        else:
            strength = None
        return {"factor_type": "large_down_payment", "present": strength is not None,
                "strength": strength, "down_pct": down_pct,
                "method": f"100 - LTV {ltv} = {down_pct}% down", "citation": _CITE,
                "data_source": "entity_states.ltv", "missing_inputs": []}

    def detect_payment_shock(self, inputs: dict) -> dict:
        return {"factor_type": "payment_shock", "present": False, "strength": None,
                "method": "payment_shock_no_baseline", "citation": _CITE,
                "data_source": "current_housing_payment (not in entity_states)",
                "missing_inputs": [
                    "current_housing_payment not in entity_states",
                    "Requires borrower rental history or existing mortgage statement"]}

    def detect_all(self, inputs: dict) -> dict:
        factors = [
            self.detect_reserves(inputs),
            self.detect_low_ltv(inputs),
            self.detect_excellent_credit(inputs),
            self.detect_long_employment(inputs),
            self.detect_limited_debt(inputs),
            self.detect_large_down_payment(inputs),
            self.detect_payment_shock(inputs),
        ]
        present = [f for f in factors if f.get("present")]
        score = sum(_STRENGTH_SCORE.get(f.get("strength"), 0) for f in factors)
        if score >= 9:
            approval_level = "senior_uw_approval"
        elif score >= 5:
            approval_level = "uw_manager_approval"
        elif score >= 2:
            approval_level = "uw_approval"
        else:
            approval_level = "insufficient_factors"
        return {
            "exception_score": score, "max_possible_score": 21,
            "approval_level": approval_level, "factors_present": present,
            "factors_present_count": len(present), "factors_checked": len(factors),
            "factors": factors, "data_source": "entity_states (via cf_inputs)",
            "missing_inputs": [m for f in factors for m in f.get("missing_inputs", [])],
            "citation": _CITE,
        }


__all__ = ["CompensatingFactorsEngine", "COMPENSATING_FACTOR_RULE_KEYS",
           "load_compensating_factor_rules"]
