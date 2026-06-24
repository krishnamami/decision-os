"""Retirement / Social Security / asset-depletion / investment income resolver
(INC-E).

Qualifies the four "non-employment" income types per Fannie B3-3.1-09:
  - Social Security  : gross-up non-taxable benefit + 3-yr continuance
  - Pension/retirement: monthly benefit + 3-yr continuance
  - Asset depletion  : eligible assets (with haircuts) / amortization divisor
  - Dividend/interest : 2-year average given sufficient history

SYNC + DB-LESS (ARCHITECTURE RULES 5/6). Every threshold/factor comes from the
injected ``rules`` dict (catalogue-resolved via load_retirement_income_rules),
falling back to rule_loader.SAFE_DEFAULTS — the single sanctioned fallback (RULE
9), shared with the rest of the codebase (no local duplicate). Returns findings
in memory; never touches the DB.

SCOPE (INC-E): catalogue-driven calculators + unit tests. Only ASSET DEPLETION
has live input today (entity_states.total_liquid_assets); SS/pension/investment
have no source documents yet — those are advisory/foundation until a separate
extraction prompt populates them. Kept a SEPARATE module from the W2 resolver.
"""
from __future__ import annotations

from typing import Optional

_CITE = "Fannie B3-3.1-09"

# Catalogue rule names this resolver reads through rule_loader.
RETIREMENT_INCOME_RULE_KEYS = [
    "ss_non_taxable_gross_up_factor",
    "ss_continuance_months_required",
    "retirement_continuance_months_required",
    "asset_depletion_divisor_months",
    "asset_depletion_retirement_haircut_pct",
    "asset_depletion_cash_haircut_pct",
    "asset_depletion_equity_haircut_pct",
    "dividend_interest_history_months_required",
]

# Method-confidence heuristics (reliability of the derivation, not lending values).
_SS_CONFIDENCE = 0.95
_PENSION_CONFIDENCE = 0.95
_DEPLETION_CONFIDENCE = 0.85
_INVESTMENT_CONFIDENCE = 0.85
_EXCLUDED_CONFIDENCE = 0.90


async def load_retirement_income_rules(conn, tenant_id: str,
                                       agency: str = "fannie") -> dict:
    """Resolve every INC-E income rule from the catalogue via rule_loader. Returns
    {'values': {key: applied}, 'trace': {...}}. ASYNC snapshot path (runner) only;
    injected into RetirementIncomeResolver. Mirrors load_asset_rules (RA-4A)."""
    from core.catalogue.rule_loader import get_rule
    values, trace = {}, {}
    for key in RETIREMENT_INCOME_RULE_KEYS:
        r = await get_rule(conn, key, tenant_id, agency=agency)
        values[key] = r.get("applied")
        trace[key] = {
            "applied":     r.get("applied"),
            "governed_by": r.get("governed_by"),
            "layers":      r.get("layers", {}),
        }
    return {"values": values, "trace": trace}


class RetirementIncomeResolver:
    def __init__(self, rules: Optional[dict] = None):
        """``rules`` is the catalogue-resolved {key: value} map. Falls back to
        rule_loader.SAFE_DEFAULTS (RULE 9) — no resolver-local constants."""
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._gross_up_factor   = float(r["ss_non_taxable_gross_up_factor"])
        self._ss_continuance    = int(r["ss_continuance_months_required"])
        self._ret_continuance   = int(r["retirement_continuance_months_required"])
        self._depletion_divisor = int(r["asset_depletion_divisor_months"])
        self._ret_haircut       = float(r["asset_depletion_retirement_haircut_pct"])
        self._cash_haircut      = float(r["asset_depletion_cash_haircut_pct"])
        self._equity_haircut    = float(r["asset_depletion_equity_haircut_pct"])
        self._div_history       = int(r["dividend_interest_history_months_required"])

    # ── Social Security ─────────────────────────────────────────────────
    def qualify_ss(self, ss_data: dict) -> dict:
        ss_data = ss_data or {}
        monthly_benefit = float(ss_data.get("monthly_benefit", 0) or 0)
        is_non_taxable = ss_data.get("is_non_taxable", True)
        continuance_months = int(ss_data.get("continuance_months_remaining", 0) or 999)

        if not monthly_benefit:
            return {
                "income_type": "SOCIAL_SECURITY", "qualifying_monthly": 0,
                "confidence": 0, "method": "ss_no_benefit_found", "citation": _CITE,
                "docs_needed": ["SSA Award Letter showing monthly benefit amount"],
                "excluded_reason": "No SS benefit amount found",
            }
        if continuance_months < self._ss_continuance:
            return {
                "income_type": "SOCIAL_SECURITY", "qualifying_monthly": 0,
                "confidence": _EXCLUDED_CONFIDENCE, "method": "ss_excluded_continuance",
                "citation": _CITE,
                "docs_needed": ["SSA Award Letter confirming benefit continuation"],
                "excluded_reason": (f"SS continuance {continuance_months}mo < "
                                    f"{self._ss_continuance}mo required"),
            }
        grossed_up = (monthly_benefit * self._gross_up_factor
                      if is_non_taxable else monthly_benefit)
        return {
            "income_type": "SOCIAL_SECURITY",
            "qualifying_monthly": round(grossed_up, 2),
            "gross_up_applied": is_non_taxable,
            "gross_up_factor": self._gross_up_factor,
            "raw_benefit": monthly_benefit,
            "method": (f"SS benefit {monthly_benefit} x {self._gross_up_factor} gross-up"
                       if is_non_taxable else f"SS benefit {monthly_benefit} (taxable)"),
            "confidence": _SS_CONFIDENCE, "citation": _CITE, "docs_needed": [],
        }

    # ── Pension / retirement ────────────────────────────────────────────
    def qualify_pension(self, pension_data: dict) -> dict:
        pension_data = pension_data or {}
        monthly_amount = float(pension_data.get("monthly_amount", 0) or 0)
        continuance_months = int(pension_data.get("continuance_months_remaining", 0) or 999)
        is_survivor_benefit = pension_data.get("is_survivor_benefit", False)

        if not monthly_amount:
            return {
                "income_type": "RETIREMENT", "qualifying_monthly": 0,
                "confidence": 0, "method": "pension_no_amount_found", "citation": _CITE,
                "docs_needed": ["Pension/retirement benefit letter showing monthly amount"],
                "excluded_reason": "No pension amount found",
            }
        if continuance_months < self._ret_continuance:
            return {
                "income_type": "RETIREMENT", "qualifying_monthly": 0,
                "confidence": _EXCLUDED_CONFIDENCE,
                "method": "pension_excluded_continuance", "citation": _CITE,
                "docs_needed": ["Award letter confirming 3-year continuance"],
                "excluded_reason": (f"Pension continuance {continuance_months}mo < "
                                    f"{self._ret_continuance}mo required"),
            }
        return {
            "income_type": "RETIREMENT",
            "qualifying_monthly": round(monthly_amount, 2),
            "is_survivor_benefit": is_survivor_benefit,
            "method": "pension_monthly_benefit",
            "confidence": _PENSION_CONFIDENCE, "citation": _CITE, "docs_needed": [],
        }

    # ── Asset depletion ─────────────────────────────────────────────────
    def qualify_asset_depletion(self, asset_data: dict) -> dict:
        asset_data = asset_data or {}
        cash_savings = float(asset_data.get("cash_savings", 0) or 0)
        retirement_assets = float(asset_data.get("retirement_assets", 0) or 0)
        equity_assets = float(asset_data.get("equity_assets", 0) or 0)
        down_payment = float(asset_data.get("down_payment_used", 0) or 0)
        closing_costs = float(asset_data.get("closing_costs_used", 0) or 0)

        eligible_cash = cash_savings * (self._cash_haircut / 100)
        eligible_retirement = retirement_assets * (self._ret_haircut / 100)
        eligible_equity = equity_assets * (self._equity_haircut / 100)

        total_eligible = max(0, eligible_cash + eligible_retirement + eligible_equity
                             - down_payment - closing_costs)
        monthly_depletion = round(total_eligible / self._depletion_divisor, 2)

        return {
            "income_type": "ASSET_DEPLETION",
            "qualifying_monthly": monthly_depletion,
            "total_eligible_assets": total_eligible,
            "eligible_cash": eligible_cash,
            "eligible_retirement": eligible_retirement,
            "eligible_equity": eligible_equity,
            "depletion_divisor": self._depletion_divisor,
            "method": (f"eligible_assets {total_eligible} / "
                       f"{self._depletion_divisor} months"),
            "confidence": _DEPLETION_CONFIDENCE, "citation": _CITE,
            "docs_needed": ([] if total_eligible > 0
                            else ["Asset statements showing eligible assets"]),
        }

    # ── Dividend / interest ─────────────────────────────────────────────
    def qualify_dividends_interest(self, investment_data: dict) -> dict:
        investment_data = investment_data or {}
        div_yr1 = float(investment_data.get("dividends_year1", 0) or 0)
        div_yr2 = float(investment_data.get("dividends_year2", 0) or 0)
        int_yr1 = float(investment_data.get("interest_year1", 0) or 0)
        int_yr2 = float(investment_data.get("interest_year2", 0) or 0)
        history_months = int(investment_data.get("history_months", 0) or 0)

        total_yr1 = div_yr1 + int_yr1
        total_yr2 = div_yr2 + int_yr2

        if history_months < self._div_history:
            return {
                "income_type": "INVESTMENT", "qualifying_monthly": 0,
                "confidence": _EXCLUDED_CONFIDENCE,
                "method": "dividends_excluded_insufficient_history", "citation": _CITE,
                "docs_needed": [
                    f"2-year dividend/interest history required "
                    f"({history_months}mo provided)",
                    "2 years tax returns showing dividend/interest income",
                ],
                "excluded_reason": (f"History {history_months}mo < "
                                    f"{self._div_history}mo required"),
            }
        two_year_avg_monthly = round((total_yr1 + total_yr2) / 24, 2)
        return {
            "income_type": "INVESTMENT",
            "qualifying_monthly": two_year_avg_monthly,
            "annual_amount": two_year_avg_monthly * 12,
            "method": (f"2yr avg dividends+interest ({total_yr1}+{total_yr2})/24"),
            "confidence": _INVESTMENT_CONFIDENCE, "citation": _CITE, "docs_needed": [],
        }


__all__ = ["RetirementIncomeResolver", "RETIREMENT_INCOME_RULE_KEYS",
           "load_retirement_income_rules"]
