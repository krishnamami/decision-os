"""MI-E — multi-borrower income + asset resolver (foundation).

Combines qualifying income and liquid assets across borrowers and applies the
Fannie B2-2-04 non-occupant co-borrower treatment. Sync + DB-less (RULE 5/6):
the caller passes the borrower list / entity_states dict, the resolver reads its
thresholds from the injected catalogue rules (SAFE_DEFAULTS fallback, RULE 1/9),
and returns findings in memory. RULE 11: data_source + missing_inputs on every
method.

Reuses income_aggregator's role vocabulary (BORROWER_ROLES) — no duplicate constants.

DATA REALITY (meridian = foundation): co-borrower data is absent — income_sources is
empty for all tenants, co_borrower_qualifying_monthly is 0/null, co_borrowers is []
for 15/16 apps, and per-borrower occupancy/assets are not extracted. So every method
degrades to single_borrower / not_applicable + missing_inputs until PATH-2 ingestion
supplies co-borrower income, occupancy, and per-borrower assets. Advisory only — not
wired into any persona.
"""
from __future__ import annotations

from typing import Optional

from core.income.income_aggregator import BORROWER_ROLES  # (primary, co_borrower, non_occupant)

MULTI_BORROWER_RULE_KEYS = [
    "non_occupant_co_borrower_max_ltv_pct",
    "non_occupant_co_borrower_occupant_must_qualify",
]

ROLE_PRIMARY, ROLE_CO_BORROWER, ROLE_NON_OCCUPANT = BORROWER_ROLES
_OCCUPANT_MAX_DTI = 45.0  # standard back-end max for the independent-qualification check


async def load_multi_borrower_rules(conn, tenant_id: str, agency: str = "fannie") -> dict:
    from core.catalogue.rule_loader import get_rule
    values, trace = {}, {}
    for key in MULTI_BORROWER_RULE_KEYS:
        r = await get_rule(conn, key, tenant_id, agency=agency)
        values[key] = r.get("applied")
        trace[key] = {"applied": r.get("applied"), "governed_by": r.get("governed_by")}
    return {"values": values, "trace": trace}


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


class MultiBorrowerResolver:
    def __init__(self, rules: Optional[dict] = None):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._non_occupant_max_ltv = _f(r.get("non_occupant_co_borrower_max_ltv_pct", 95))
        self._occupant_must_qualify = bool(r.get("non_occupant_co_borrower_occupant_must_qualify", True))

    # ── income stacking ───────────────────────────────────────────────────────
    def combine_income(self, borrowers: list) -> dict:
        if not borrowers:
            return {"status": "single_borrower", "combined_monthly": 0.0, "borrower_count": 0,
                    "by_role": {}, "method": "no_borrowers_provided", "citation": "Fannie B3-3.1-01",
                    "data_source": "entity_states.qualifying_monthly + co_borrowers JSONB",
                    "missing_inputs": ["borrowers list empty — single-borrower application"]}
        primary = [b for b in borrowers if b.get("role") == ROLE_PRIMARY]
        if not primary:
            return {"status": "error", "combined_monthly": 0.0, "method": "no_primary_borrower",
                    "citation": "Fannie B3-3.1-01", "data_source": "borrowers list",
                    "missing_inputs": ["no primary borrower in list — required"]}
        co = [b for b in borrowers if b.get("role") == ROLE_CO_BORROWER]
        non_occ = [b for b in borrowers if b.get("role") == ROLE_NON_OCCUPANT]
        p_inc = sum(_f(b.get("qualifying_monthly")) for b in primary)
        c_inc = sum(_f(b.get("qualifying_monthly")) for b in co)
        n_inc = sum(_f(b.get("qualifying_monthly")) for b in non_occ)
        missing = [f"{b.get('role','unknown')}.qualifying_monthly not extracted"
                   for b in borrowers if b.get("qualifying_monthly") is None]
        return {
            "status": "combined", "combined_monthly": round(p_inc + c_inc + n_inc, 2),
            "primary_monthly": round(p_inc, 2), "co_borrower_monthly": round(c_inc, 2),
            "non_occupant_monthly": round(n_inc, 2), "borrower_count": len(borrowers),
            "has_non_occupant": bool(non_occ),
            "by_role": {ROLE_PRIMARY: round(p_inc, 2), ROLE_CO_BORROWER: round(c_inc, 2),
                        ROLE_NON_OCCUPANT: round(n_inc, 2)},
            "method": f"stacked {len(borrowers)} borrower(s) across roles",
            "citation": "Fannie B3-3.1-01 + B2-2-04",
            "data_source": "entity_states.qualifying_monthly + co_borrowers JSONB",
            "missing_inputs": missing}

    # ── Fannie B2-2-04 non-occupant treatment ─────────────────────────────────
    def evaluate_non_occupant(self, occupant_dti, occupant_income, current_ltv,
                              has_non_occupant: bool) -> dict:
        if not has_non_occupant:
            return {"applies": False, "reason": "no_non_occupant_co_borrower", "ltv_cap": None,
                    "occupant_must_independently_qualify": False, "citation": "Fannie B2-2-04",
                    "data_source": "entity_states.co_borrowers[].is_occupant", "missing_inputs": []}
        ltv = _f(current_ltv)
        ltv_over_cap = ltv > self._non_occupant_max_ltv if ltv else False
        occ_dti = _f(occupant_dti) if occupant_dti is not None else None
        occ_ok, occ_note, missing = True, None, []
        if occupant_dti is None:
            missing.append("occupant_dti (primary-only) not available")
        elif self._occupant_must_qualify:
            occ_ok = occ_dti <= _OCCUPANT_MAX_DTI
            if not occ_ok:
                occ_note = (f"occupant DTI {occ_dti:.1f}% exceeds {_OCCUPANT_MAX_DTI:.0f}% — "
                            f"occupant must independently qualify (B2-2-04)")
        docs = ["Non-occupant co-borrower documentation per Fannie B2-2-04"]
        if ltv_over_cap:
            docs.append(f"Reduce LTV to {self._non_occupant_max_ltv:.0f}% or below")
        if occ_note:
            docs.append(occ_note)
        return {
            "applies": True, "ltv_cap": self._non_occupant_max_ltv, "ltv_over_cap": ltv_over_cap,
            "current_ltv": ltv, "occupant_must_independently_qualify": self._occupant_must_qualify,
            "occupant_dti": occ_dti, "occupant_qualifies_independently": occ_ok,
            "occupant_dti_note": occ_note, "docs_needed": docs, "citation": "Fannie B2-2-04",
            "data_source": "entity_states.ltv + entity_states.dti_back", "missing_inputs": missing}

    # ── asset stacking ─────────────────────────────────────────────────────────
    def combine_assets(self, borrowers: list, total_liquid_assets=None) -> dict:
        if total_liquid_assets is not None:
            return {"status": "combined", "combined_assets": _f(total_liquid_assets),
                    "method": "entity_states_scalar", "citation": "Fannie B3-4.1-01",
                    "data_source": "entity_states.total_liquid_assets",
                    "note": "per-borrower asset breakdown not yet extracted; using combined scalar",
                    "missing_inputs": ["per_borrower_liquid_assets not in co_borrowers JSONB"]}
        if not borrowers:
            return {"status": "not_applicable", "combined_assets": 0.0, "method": "no_borrowers",
                    "citation": "Fannie B3-4.1-01", "data_source": "co_borrowers JSONB",
                    "missing_inputs": ["no borrowers and no total_liquid_assets scalar"]}
        per, total, missing = [], 0.0, []
        for b in borrowers:
            a = b.get("liquid_assets")
            if a is None:
                missing.append(f"{b.get('role','unknown')}.liquid_assets not provided")
            else:
                total += _f(a)
                per.append({"role": b.get("role"), "assets": _f(a)})
        return {"status": "combined" if not missing else "partial",
                "combined_assets": round(total, 2), "per_borrower": per,
                "method": f"summed {len(per)} borrower asset account(s)",
                "citation": "Fannie B3-4.1-01", "data_source": "co_borrowers[].liquid_assets",
                "missing_inputs": missing}

    # ── full resolution from an entity_states dict ────────────────────────────
    def resolve(self, entity_states: dict, borrowers: Optional[list] = None) -> dict:
        import json as _json
        es = entity_states or {}
        primary_income = _f(es.get("qualifying_monthly"))
        co_income = _f(es.get("co_borrower_qualifying_monthly"))
        total_assets = es.get("total_liquid_assets")
        current_ltv = _f(es.get("ltv"))
        current_dti = es.get("dti_back")

        if borrowers is None:
            co_data = es.get("co_borrowers")
            if isinstance(co_data, str):
                try:
                    co_data = _json.loads(co_data)
                except Exception:
                    co_data = []
            co_data = co_data or []
            borrowers = [{"role": ROLE_PRIMARY, "qualifying_monthly": primary_income}]
            if co_income > 0:
                borrowers.append({"role": ROLE_CO_BORROWER, "qualifying_monthly": co_income})
            else:
                for cb in co_data:
                    role = ROLE_CO_BORROWER if cb.get("is_occupant", True) else ROLE_NON_OCCUPANT
                    borrowers.append({"role": role,
                                      "qualifying_monthly": _f(cb.get("qualifying_monthly")),
                                      "liquid_assets": cb.get("liquid_assets")})

        income = self.combine_income(borrowers)
        assets = self.combine_assets(borrowers, total_liquid_assets=total_assets)
        has_non_occ = any(b.get("role") == ROLE_NON_OCCUPANT for b in borrowers)
        non_occ = self.evaluate_non_occupant(
            occupant_dti=current_dti, occupant_income=primary_income,
            current_ltv=current_ltv, has_non_occupant=has_non_occ)
        is_single = len(borrowers) <= 1 or income["combined_monthly"] <= primary_income
        return {
            "borrower_count": len(borrowers), "is_single_borrower": is_single,
            "income": income, "assets": assets, "non_occupant": non_occ,
            "combined_monthly": income["combined_monthly"],
            "combined_assets": assets["combined_assets"],
            "citation": "Fannie B3-3.1-01 + B2-2-04 + B3-4.1-01",
            "data_source": "entity_states + co_borrowers JSONB",
            "missing_inputs": income["missing_inputs"] + assets["missing_inputs"]}


__all__ = ["MultiBorrowerResolver", "load_multi_borrower_rules", "MULTI_BORROWER_RULE_KEYS"]
