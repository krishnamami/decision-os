"""CO-D — ADU + multi-unit rental income resolver.

Qualifying income for subject owner-occupied 2-4 unit properties and ADUs, plus
the non-owner-occupied (investment) 2-4 unit case. Sync + DB-less (RULE 5/6): the
caller passes the inputs, the resolver reads its factors from the injected catalogue
rules (SAFE_DEFAULTS fallback, RULE 1/9), and returns findings in memory. RULE 11:
`data_source` + `missing_inputs` on every method.

This SITS ON TOP of INC-D's RentalIncomeResolver (Schedule E net rental) — it does
not duplicate it; `qualify_investment_multi_unit` consumes that net-rental output.

DATA REALITY (meridian = foundation, like INC-E/F): the inputs that distinguish a
multi-unit / ADU loan are NOT extracted today —
  num_units          entity_states.property.num_units      (absent)  -> missing_inputs
  adu_present        entity_states.property.adu_present     (absent)  -> missing_inputs
  gross_market_rent  Form 1007 / 1025 extracted_fields      (absent)  -> missing_inputs
  net_rental_income  INC-D RentalIncomeResolver (Schedule E) available when present
  piti_monthly       entity_states.piti_monthly             available
  occupancy_type     entity_states.loan_terms / urla        available
So every method degrades to `not_applicable` + `missing_inputs` until PATH-2 Form
1004/1007/1025 extraction supplies the unit + market-rent fields. Advisory only.
"""
from __future__ import annotations

from typing import Optional

MULTI_UNIT_RULE_KEYS = [
    "market_rent_qualifying_factor_pct",
    "subject_2_4_unit_rental_factor",
    "adu_rental_income_allowed",
    "adu_owner_occupancy_required",
    "adu_max_units",
    "rental_vacancy_factor_pct",  # shared with INC-D
]


async def load_multi_unit_rules(conn, tenant_id: str, agency: str = "fannie") -> dict:
    from core.catalogue.rule_loader import get_rule
    values, trace = {}, {}
    for key in MULTI_UNIT_RULE_KEYS:
        r = await get_rule(conn, key, tenant_id, agency=agency)
        values[key] = r.get("applied")
        trace[key] = {"applied": r.get("applied"), "governed_by": r.get("governed_by")}
    return {"values": values, "trace": trace}


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


class MultiUnitIncomeResolver:
    """Sync, DB-less. All factors from the injected catalogue rules dict."""

    def __init__(self, rules: Optional[dict] = None):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._market_rent_factor = _f(r.get("market_rent_qualifying_factor_pct", 75)) / 100.0
        self._subject_rental_factor = _f(r.get("subject_2_4_unit_rental_factor", 75)) / 100.0
        self._adu_allowed = bool(r.get("adu_rental_income_allowed", True))
        self._adu_owner_required = bool(r.get("adu_owner_occupancy_required", True))
        self._adu_max_units = int(_f(r.get("adu_max_units", 1)))
        self._vacancy_factor = _f(r.get("rental_vacancy_factor_pct", 25)) / 100.0

    # ── subject owner-occupied 2-4 unit ──────────────────────────────────────
    def qualify_subject_multi_unit(self, inputs: dict) -> dict:
        """Owner-occupied subject 2-4 unit: 75% of gross market rent from the
        non-owner units, net of PITI. Positive net -> income; negative -> a
        shortfall the DTI layer would treat as an obligation (we never invent
        income from a loss)."""
        inputs = inputs or {}
        num_units = inputs.get("num_units")
        gross_market_rent = inputs.get("gross_market_rent_per_unit")
        piti_monthly = _f(inputs.get("piti_monthly", 0))
        occupancy = str(inputs.get("occupancy_type", "primary") or "primary").lower()
        is_owner_occupied = inputs.get("is_owner_occupied", "primary" in occupancy)

        missing = []
        if num_units is None:
            missing.append("num_units not in entity_states.property — extract from "
                           "APPRAISAL_URAR / Form 1025")
        if gross_market_rent is None:
            missing.append("gross_market_rent_per_unit not available — requires "
                           "Form 1007/1025 extraction")
        if missing:
            return self._na("MULTI_UNIT_SUBJECT", "multi_unit_subject_not_applicable",
                            "Fannie B3-3.1-08", "entity_states.property + Form 1025", missing,
                            note="PATH 2: extract num_units + market rent from Form 1004/1025.")

        n = int(_f(num_units))
        if n < 2 or n > 4:
            return self._excluded("MULTI_UNIT_SUBJECT", "multi_unit_subject_ineligible",
                                  "Fannie B2-1.1-01", "entity_states.property.num_units",
                                  f"Property has {n} units — must be 2-4 for multi-unit treatment")
        if not is_owner_occupied:
            return self._excluded("MULTI_UNIT_SUBJECT", "multi_unit_investment_not_subject",
                                  "Fannie B3-3.1-08", "entity_states.loan_terms.occupancy_type",
                                  "Non-owner-occupied 2-4 unit — use investment rental rules "
                                  "(qualify_investment_multi_unit), not subject treatment")

        rental_units = n - 1  # owner occupies one
        gross_monthly = _f(gross_market_rent) * rental_units
        qualifying_rental = round(gross_monthly * self._subject_rental_factor, 2)
        net_cash_flow = round(qualifying_rental - piti_monthly, 2)
        return {
            "income_type": "MULTI_UNIT_SUBJECT",
            "qualifying_monthly": max(0.0, net_cash_flow),
            "gross_market_rent_monthly": round(gross_monthly, 2),
            "qualifying_rental": qualifying_rental,
            "rental_factor": self._subject_rental_factor,
            "rental_units": rental_units,
            "piti_monthly": piti_monthly,
            "net_cash_flow": net_cash_flow,
            "is_shortfall": net_cash_flow < 0,
            "method": (f"{rental_units} rental unit(s) x ${_f(gross_market_rent):,.0f} x "
                       f"{self._subject_rental_factor*100:.0f}% = ${qualifying_rental:,.0f}/mo, "
                       f"net of PITI ${piti_monthly:,.0f} = ${net_cash_flow:,.0f}"),
            "confidence": 0.85,
            "citation": "Fannie B3-3.1-08 / Form 1007",
            "data_source": "entity_states.property.num_units + Form 1025 + "
                           "entity_states.piti_monthly",
            "missing_inputs": [],
            "docs_needed": ["Form 1025 (Small Residential Income Property Appraisal)"],
        }

    # ── ADU (HomeReady) ──────────────────────────────────────────────────────
    def qualify_adu_income(self, inputs: dict) -> dict:
        inputs = inputs or {}
        if not self._adu_allowed:
            return self._excluded("ADU", "adu_not_allowed_by_overlay",
                                  "Fannie HomeReady B5-6-01",
                                  "overlay_rules.adu_rental_income_allowed",
                                  "ADU income disabled by lender overlay")
        adu_present = inputs.get("adu_present")
        adu_market_rent = inputs.get("adu_market_rent_monthly")
        occupancy = str(inputs.get("occupancy_type", "primary") or "primary").lower()

        missing = []
        if adu_present is None:
            missing.append("adu_present flag not in entity_states.property — extract "
                           "from the appraisal ADU section")
        if adu_market_rent is None:
            missing.append("adu_market_rent_monthly not available — requires Form 1007 "
                           "extraction")
        if missing:
            return self._na("ADU", "adu_not_applicable", "Fannie HomeReady B5-6-01",
                            "entity_states.property.adu_present + Form 1007", missing,
                            note="PATH 2: extract from Form 1007 (Single-Family Comparable Rent).")

        if not adu_present:
            return self._excluded("ADU", "adu_not_present", "Fannie HomeReady B5-6-01",
                                  "entity_states.property.adu_present", "No ADU on this property")
        if self._adu_owner_required and "primary" not in occupancy:
            return self._excluded("ADU", "adu_excluded_not_owner_occupied",
                                  "Fannie HomeReady B5-6-01",
                                  "entity_states.loan_terms.occupancy_type",
                                  "ADU income requires owner-occupancy (HomeReady)")

        qualifying = round(_f(adu_market_rent) * self._market_rent_factor, 2)
        return {
            "income_type": "ADU", "qualifying_monthly": qualifying,
            "adu_market_rent": _f(adu_market_rent),
            "qualifying_factor": self._market_rent_factor,
            "method": (f"ADU market rent ${_f(adu_market_rent):,.0f} x "
                       f"{self._market_rent_factor*100:.0f}% = ${qualifying:,.0f}/mo"),
            "confidence": 0.85, "citation": "Fannie HomeReady B5-6-01 / Form 1007",
            "data_source": "entity_states.property.adu_present + Form 1007.adu_market_rent",
            "missing_inputs": [],
            "docs_needed": ["Form 1007 (Single-Family Comparable Rent Schedule)"],
        }

    # ── non-owner-occupied 2-4 unit (investment) — reuses INC-D net rental ────
    def qualify_investment_multi_unit(self, inputs: dict) -> dict:
        inputs = inputs or {}
        net_rental_income = _f(inputs.get("net_rental_income", 0))
        piti_monthly = _f(inputs.get("piti_monthly", 0))
        num_units = inputs.get("num_units")
        has_schedule_e = bool(inputs.get("has_schedule_e", False))

        missing = []
        if num_units is None:
            missing.append("num_units not in entity_states.property")
        if not has_schedule_e and not net_rental_income:
            missing.append("net_rental_income requires Schedule E (INC-D "
                           "RentalIncomeResolver) output")
        if missing and not net_rental_income:
            return self._na("MULTI_UNIT_INVESTMENT", "investment_multi_unit_not_applicable",
                            "Fannie B3-3.1-08", "rental_income_resolver + entity_states", missing)

        net_cf = round(net_rental_income - piti_monthly, 2)
        return {
            "income_type": "MULTI_UNIT_INVESTMENT",
            "qualifying_monthly": max(0.0, net_cf),
            "net_rental_income": net_rental_income, "piti_monthly": piti_monthly,
            "net_cash_flow": net_cf, "is_shortfall": net_cf < 0,
            "method": (f"net rental ${net_rental_income:,.0f} - PITI ${piti_monthly:,.0f} "
                       f"= ${net_cf:,.0f}"),
            "confidence": 0.85, "citation": "Fannie B3-3.1-08",
            "data_source": "rental_income_resolver.net_rental_income (INC-D) + "
                           "entity_states.piti_monthly",
            "missing_inputs": missing,  # num_units may still be missing (informational)
        }

    # ── RULE 11 helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _na(income_type, method, citation, data_source, missing, note=None) -> dict:
        out = {"income_type": income_type, "qualifying_monthly": 0.0, "method": method,
               "confidence": 0.0, "citation": citation, "data_source": data_source,
               "missing_inputs": missing}
        if note:
            out["note"] = note
        return out

    @staticmethod
    def _excluded(income_type, method, citation, data_source, reason) -> dict:
        return {"income_type": income_type, "qualifying_monthly": 0.0, "method": method,
                "confidence": 0.95, "citation": citation, "data_source": data_source,
                "missing_inputs": [], "excluded_reason": reason}


__all__ = ["MultiUnitIncomeResolver", "load_multi_unit_rules", "MULTI_UNIT_RULE_KEYS"]
