"""FR-F — VA residual income check (VA Pamphlet 26-7 Chapter 4).

Residual income = the money left after taxes + PITI + obligations + maintenance.
VA requires it to meet a regional, family-size-based minimum. Sync + DB-less
(RULE 5/6): the caller passes the inputs, the resolver reads its estimate scalars
from the injected catalogue rules (regulatory layer, SAFE_DEFAULTS fallback), and
returns findings in memory. RULE 11: data_source + missing_inputs on every output.

The residual TABLE + region map are fixed VA regulatory reference data hosted as
cited code constants (like the LLPA grid / county limits) — NOT catalogue rows.
Only the estimate scalars (maintenance/sqft, tax %, min-loan) are catalogue-driven.

DATA REALITY (meridian = foundation): all 16 meridian loans are loan_type='other'
(0 VA), and family_size is not extracted — so every call returns not_applicable
(non-VA) or missing_inputs (family_size drives the table row, never guessed).
Standalone — NOT wired into the 16/16-critical compliance_check/product_eligibility.
"""
from __future__ import annotations

from typing import Optional

VA_RULE_KEYS = [
    "va_residual_maintenance_per_sqft_monthly",
    "va_residual_tax_estimate_pct",
    "va_residual_min_loan_amount",
]

# VA Pamphlet 26-7 Ch.4 — required monthly residual, loan >= $80,000.
VA_RESIDUAL_TABLE = {
    1: {"northeast": 450, "midwest": 441, "south": 441, "west": 491},
    2: {"northeast": 755, "midwest": 738, "south": 738, "west": 823},
    3: {"northeast": 909, "midwest": 889, "south": 889, "west": 990},
    4: {"northeast": 1025, "midwest": 1003, "south": 1003, "west": 1117},
    5: {"northeast": 1062, "midwest": 1039, "south": 1039, "west": 1158},
}
VA_RESIDUAL_PER_ADDITIONAL_PERSON = 80  # for family_size > 5

REGION_BY_STATE = {
    **{s: "northeast" for s in ("CT", "ME", "MA", "NH", "NJ", "NY", "PA", "RI", "VT")},
    **{s: "midwest" for s in ("IL", "IN", "IA", "KS", "MI", "MN", "MO", "NE", "ND",
                              "OH", "SD", "WI")},
    **{s: "south" for s in ("AL", "AR", "DE", "DC", "FL", "GA", "KY", "LA", "MD", "MS",
                            "NC", "OK", "SC", "TN", "TX", "VA", "WV")},
    **{s: "west" for s in ("AK", "AZ", "CA", "CO", "HI", "ID", "MT", "NV", "NM", "OR",
                           "UT", "WA", "WY")},
}


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


async def load_va_residual_rules(conn, tenant_id: str) -> dict:
    from core.catalogue.rule_loader import get_rule
    values, trace = {}, {}
    for key in VA_RULE_KEYS:
        r = await get_rule(conn, key, tenant_id, agency="va")
        values[key] = r.get("applied")
        trace[key] = {"applied": r.get("applied"), "governed_by": r.get("governed_by")}
    return {"values": values, "trace": trace}


class VAResidualIncomeResolver:
    def __init__(self, rules: Optional[dict] = None):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._maintenance_rate = _f(r.get("va_residual_maintenance_per_sqft_monthly", 0.14))
        self._tax_estimate_pct = _f(r.get("va_residual_tax_estimate_pct", 25))
        self._min_loan_amt = _f(r.get("va_residual_min_loan_amount", 80000))

    @staticmethod
    def _region(state: str) -> Optional[str]:
        return REGION_BY_STATE.get((state or "").upper())

    def _required_residual(self, family_size: int, region: str) -> int:
        fs = max(1, int(family_size))
        if fs <= 5:
            return VA_RESIDUAL_TABLE[fs][region]
        # > 5: the 5-person base plus a per-additional-person increment (computed
        # BEFORE any clamp — clamping first would make this dead code).
        return VA_RESIDUAL_TABLE[5][region] + (fs - 5) * VA_RESIDUAL_PER_ADDITIONAL_PERSON

    def qualify_va_residual(self, inputs: dict) -> dict:
        inputs = inputs or {}
        loan_type = str(inputs.get("loan_type") or "").lower()
        if "va" not in loan_type:
            return self._na(f"loan_type {loan_type!r} is not VA", "va_not_applicable",
                            "entity_states.loan_terms.loan_type", [])

        gross = _f(inputs.get("qualifying_monthly"))
        piti = _f(inputs.get("piti_monthly"))
        obligations = _f(inputs.get("monthly_obligations"))
        state = str(inputs.get("property_state") or "").upper()
        family_size = inputs.get("family_size")
        sqft = inputs.get("gross_living_area")
        loan_amount = _f(inputs.get("loan_amount"))

        missing = []
        if not gross:
            missing.append("qualifying_monthly not in entity_states")
        if not piti:
            missing.append("piti_monthly not in entity_states")
        if family_size is None:
            missing.append("family_size not in borrower JSONB — required to pick the VA "
                           "residual table row (never assumed)")
        region = self._region(state)
        if region is None:
            missing.append(f"property_state {state!r} not mapped to a VA region")
        if missing:
            return self._na("missing_required_inputs", "va_residual_missing_inputs",
                            "entity_states + borrower.family_size", missing)

        # tax estimate (heuristic — actual taxes not extracted)
        tax_monthly = round(gross * (self._tax_estimate_pct / 100.0) / 12.0, 2)
        tax_missing = ["federal_income_tax not extracted — using estimate"]
        # maintenance (needs sqft from APPRAISAL_URAR.gross_living_area)
        if sqft:
            maintenance = round(_f(sqft) * self._maintenance_rate, 2)
            maint_method = f"{_f(sqft):.0f} sqft x ${self._maintenance_rate}/sqft"
            maint_missing = []
        else:
            maintenance = 0.0
            maint_method = "gross_living_area unavailable — maintenance excluded"
            maint_missing = ["gross_living_area not in entity_states — extract from "
                             "APPRAISAL_URAR.gross_living_area"]

        residual = round(gross - tax_monthly - piti - obligations - maintenance, 2)
        fs = int(family_size)

        if loan_amount and loan_amount < self._min_loan_amt:
            return {
                "status": "not_applicable",
                "reason": f"loan_amount ${loan_amount:,.0f} < ${self._min_loan_amt:,.0f} "
                          f"(small-loan residual table not hosted)",
                "residual": residual, "required": None, "passes": None,
                "method": "va_residual_small_loan_table", "citation": "VA Pamphlet 26-7 Ch.4",
                "data_source": "entity_states.loan_amount",
                "missing_inputs": ["VA small-loan (<$80k) residual table not hosted"]}

        required = self._required_residual(fs, region)
        passes = residual >= required
        return {
            "status": "pass" if passes else "fail",
            "residual": residual, "required": required, "passes": passes,
            "shortfall": round(required - residual, 2) if not passes else 0.0,
            "region": region, "family_size": fs, "state": state,
            "breakdown": {"gross_monthly": gross, "tax_monthly": tax_monthly,
                          "tax_method": f"estimated at {self._tax_estimate_pct:.0f}% annual",
                          "piti_monthly": piti, "obligations": obligations,
                          "maintenance": maintenance, "maintenance_method": maint_method},
            "method": (f"VA residual ${gross:,.0f} - ${tax_monthly:,.0f} tax - ${piti:,.0f} "
                       f"PITI - ${obligations:,.0f} oblig - ${maintenance:,.0f} maint = "
                       f"${residual:,.0f} vs required ${required:,.0f} "
                       f"({region}, family {fs})"),
            "citation": "VA Pamphlet 26-7 Ch.4",
            "data_source": "entity_states + VA_RESIDUAL_TABLE (code constant)",
            "missing_inputs": tax_missing + maint_missing,
            "docs_needed": ([f"VA residual shortfall ${required - residual:,.0f} below "
                             f"${required:,.0f} (family {fs}, {region})"]
                            if not passes else [])}

    @staticmethod
    def _na(reason, method, data_source, missing) -> dict:
        return {"status": "not_applicable", "reason": reason, "residual": None,
                "required": None, "passes": None, "method": method,
                "citation": "VA Pamphlet 26-7 Ch.4", "data_source": data_source,
                "missing_inputs": missing}


__all__ = ["VAResidualIncomeResolver", "load_va_residual_rules", "VA_RULE_KEYS",
           "VA_RESIDUAL_TABLE", "REGION_BY_STATE"]
