"""Exception eligibility engine (EX-A).

Evaluates whether a blocked decision is eligible for an underwriting EXCEPTION
(overlay breach) and what it would take to grant one, per Fannie B3-2-02. SYNC +
DB-LESS (RULES 5/6); thresholds from the injected ``rules`` dict (catalogue), with
rule_loader.SAFE_DEFAULTS as the only fallback (RULE 9). Returns findings in
memory; never writes the DB.

Three gates (in order):
  1. Agency floor is ABSOLUTE — below it, no exception is ever possible.
  2. Overlay breach tolerance — beyond max breach %, no exception.
  3. Compensating factors — required (catalogue) before an eligible exception
     may actually be granted.

Builds ON the existing override capture (loan_actions + decision_outputs.human_*);
does NOT duplicate it. ADVISORY — wired into approval_routing as output only; never
moves proposed_outcome (Known Gap f stands). EX-B/C populate loan_exceptions /
compensating_factors. RULE 11: every return carries `data_source` + `missing_inputs`.
"""
from __future__ import annotations

from typing import Optional

_CITE = "Fannie B3-2-02"

EXCEPTION_RULE_KEYS = [
    "exception_requires_compensating_factors",
    "exception_max_dti_overlay_breach_pct",
    "exception_max_ltv_overlay_breach_pct",
    "exception_cannot_breach_agency_floor",
    # EX-B — compensating-factor bar thresholds ride on the SAME exception_rules
    # bundle key (one runner branch); CompensatingFactorsEngine reads them.
    "substantial_reserves_months",
    "exceptional_reserves_months",
    "low_ltv_factor_max_pct",
    "excellent_credit_delta_pts",
    "long_employment_months",
    "minimal_debt_obligations_max_pct",
    "minimum_reserves_months",   # baseline floor (already seeded)
]


async def load_exception_rules(conn, tenant_id: str, agency: str = "fannie") -> dict:
    """Resolve the EX-A exception rules from the catalogue via rule_loader.
    {'values': {key: applied}, 'trace': {...}}. ASYNC snapshot path (runner) only;
    injected into ExceptionEngine. Mirrors load_asset_rules (RA-4A)."""
    from core.catalogue.rule_loader import get_rule
    values, trace = {}, {}
    for key in EXCEPTION_RULE_KEYS:
        r = await get_rule(conn, key, tenant_id, agency=agency)
        values[key] = r.get("applied")
        trace[key] = {
            "applied":     r.get("applied"),
            "governed_by": r.get("governed_by"),
            "layers":      r.get("layers", {}),
        }
    return {"values": values, "trace": trace}


# Blocked-signal substring -> exception type (Fannie exception taxonomy).
_SIGNAL_MAP = {
    "DTI_EXCEEDS":    "dti_overlay_breach",
    "LTV_EXCEEDS":    "ltv_overlay_breach",
    "CREDIT_FAILS":   "credit_overlay_breach",
    "AUS_CONFLICT":   "aus_conflict",
    "ROUTE_CONFLICT": "manual_underwrite",
}


class ExceptionEngine:
    def __init__(self, rules: Optional[dict] = None):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._requires_compensating = bool(
            r.get("exception_requires_compensating_factors", True))
        self._max_dti_breach_pct = float(
            r.get("exception_max_dti_overlay_breach_pct", 5))
        self._max_ltv_breach_pct = float(
            r.get("exception_max_ltv_overlay_breach_pct", 5))
        self._cannot_breach_agency = bool(
            r.get("exception_cannot_breach_agency_floor", True))

    def evaluate_exception_eligibility(
        self,
        blocked_signal: str,
        actual_value: Optional[float],
        overlay_threshold: Optional[float],
        agency_floor: Optional[float],
        compensating_factors: Optional[list],
    ) -> dict:
        """DATA SOURCES:
          blocked_signal       -> decision_outputs.signals (existing)
          actual_value         -> entity_states (existing)
          overlay_threshold    -> overlay_rules via enricher (existing)
          agency_floor         -> agency_guidelines via catalogue (existing)
          compensating_factors -> compensating_factors table (new, EX-B/C)"""
        blocked_signal = blocked_signal or ""
        compensating_factors = compensating_factors or []
        av = None if actual_value is None else float(actual_value)

        # Gate 1 — agency floor is absolute.
        below_agency_floor = bool(
            self._cannot_breach_agency and agency_floor is not None
            and av is not None and av < float(agency_floor))
        if below_agency_floor:
            return {
                "eligible_for_exception": False, "reason": "below_agency_floor",
                "agency_floor": agency_floor, "actual_value": av,
                "note": "Cannot grant exception below agency minimum. Agency floor is absolute.",
                "citation": _CITE, "data_source": "agency_guidelines + entity_states",
                "missing_inputs": [],
            }

        # Gate 2 — overlay breach tolerance.
        if overlay_threshold not in (None, 0) and av is not None:
            breach_pct = abs(av - float(overlay_threshold)) / float(overlay_threshold) * 100
            max_breach = (self._max_dti_breach_pct if "dti" in blocked_signal.lower()
                          else self._max_ltv_breach_pct)
            if breach_pct > max_breach:
                return {
                    "eligible_for_exception": False, "reason": "breach_exceeds_maximum",
                    "breach_pct": round(breach_pct, 2), "max_breach_pct": max_breach,
                    "note": (f"Breach {breach_pct:.1f}% exceeds maximum exception "
                             f"tolerance {max_breach}%"),
                    "citation": _CITE, "data_source": "overlay_rules + entity_states",
                    "missing_inputs": [],
                }
        else:
            breach_pct = 0

        # Gate 3 — compensating factors required.
        if self._requires_compensating and not compensating_factors:
            return {
                "eligible_for_exception": True, "reason": "compensating_factors_required",
                "breach_pct": round(breach_pct, 2), "compensating_factors_count": 0,
                "note": "Exception eligible but compensating factors required before approval",
                "citation": _CITE,
                "docs_needed": [
                    "Document at least one compensating factor",
                    "Common: substantial reserves (12+ months PITI)",
                    "Common: low LTV (significantly below maximum)",
                    "Common: long employment history (5+ years)",
                ],
                "data_source": "compensating_factors table",
                "missing_inputs": ["compensating_factors (none documented yet)"],
            }

        return {
            "eligible_for_exception": True, "reason": "eligible_with_factors",
            "breach_pct": round(breach_pct, 2),
            "compensating_factors_count": len(compensating_factors),
            "compensating_factors": compensating_factors,
            "note": f"Exception eligible with {len(compensating_factors)} compensating factor(s)",
            "citation": _CITE,
            "data_source": "entity_states + overlay_rules + compensating_factors table",
            "missing_inputs": [],
        }

    def classify_exception_type(self, blocked_signal: str) -> str:
        s = (blocked_signal or "").upper()
        for key, exc_type in _SIGNAL_MAP.items():
            if key in s:
                return exc_type
        return "other"


__all__ = ["ExceptionEngine", "EXCEPTION_RULE_KEYS", "load_exception_rules"]
