"""CM-F — overlay-attributable disparate-impact analyzer (the unique CM-F piece).

CF-A generates the HMDA LAR file; CM-D detects AGGREGATE disparity. CM-F attributes
disparity to a SPECIFIC lender overlay: among loans that PASS the agency floor but
FAIL the stricter overlay, does a protected class fail at a disproportionate rate?
That isolates the overlay's MARGINAL disparate impact (the agency floor everyone
must meet is held constant).

Reuses, does not re-implement:
  - CI-A SIMULATABLE_FIELDS  -> overlay rule_type -> (entity_states field, direction)
  - CM-D HMDA_CODES / NOT_PROVIDED_CODES / PROTECTED_CLASS_COLUMN  -> demographics

Linkage uses the entity_states gate VALUE vs the overlay/agency thresholds (NOT
decision_outputs signals / upstream_decisions — both empty/NULL in live data).
Sync + pure + RULE 11. Post-decision read-only -> 16/16 by construction.

Screen: EEOC 4/5 ratio < 0.80 (federal) OR a > N percentage-point overlay-fail-rate
gap vs the reference (internal, catalogue `fair_lending_overlay_disparity_pct`).
Honest insufficient_data when <2 identifiable demographic groups (e.g. meridian, all
race/sex not-provided) — never a fabricated overlay finding.
"""
from __future__ import annotations

from typing import Optional

from core.compliance.fair_lending_monitor import (
    HMDA_CODES, NOT_PROVIDED_CODES, PROTECTED_CLASS_COLUMN,
)
from core.intelligence.change_impact_simulator import SIMULATABLE_FIELDS

# overlay rule_type -> the agency guideline name + comparison + fallback floor.
AGENCY_FLOOR_SPEC = {
    "credit_floor": ("Minimum Credit Score", False, 620),
    "dti_back_max": ("DU Maximum DTI", True, 50),
    "ltv_max_purchase": ("Primary Residence 1-Unit Max LTV", True, 97),
}
_MIN_GROUP = 5


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _passes(value: float, threshold: float, direction: str) -> bool:
    """gate pass: gte (floor) -> value >= threshold; lte (ceiling) -> value <= threshold."""
    return value >= threshold if direction == "gte" else value <= threshold


def _strictest(overlays_for_type: list, direction: str) -> Optional[float]:
    vals = [v for v in overlays_for_type if v is not None]
    if not vals:
        return None
    return max(vals) if direction == "gte" else min(vals)


class OverlayDisparityAnalyzer:
    def __init__(self, rules: Optional[dict] = None):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._four_fifths = float(r.get("fair_lending_four_fifths_ratio", 0.80))
        self._disparity_pp = float(r.get("fair_lending_overlay_disparity_pct", 20))

    def _analyze_overlay_class(self, loans, field, direction, agency, overlay,
                               protected_class) -> dict:
        col = PROTECTED_CLASS_COLUMN[protected_class]
        labels = HMDA_CODES[protected_class]
        np_codes = NOT_PROVIDED_CODES[protected_class]
        ds = f"entity_states.{field} + hmda_lar.{col}"

        # Population = loans that PASS the agency floor (the overlay only bites here),
        # grouped by identifiable protected class. overlay-fail = fails the stricter overlay.
        groups: dict = {}
        for loan in loans:
            v = _num(loan.get(field))
            if v is None:
                continue
            if not _passes(v, agency, direction):
                continue  # blocked by the agency floor anyway -> not overlay-attributable
            code = _int(loan.get(col))
            if code in np_codes or code is None:
                continue  # not an identifiable demographic
            lbl = labels.get(code, f"code_{code}")
            g = groups.setdefault(lbl, {"pass_agency": 0, "fail_overlay": 0})
            g["pass_agency"] += 1
            if not _passes(v, overlay, direction):
                g["fail_overlay"] += 1

        identifiable = {l: c for l, c in groups.items() if c["pass_agency"] >= _MIN_GROUP}
        if len(identifiable) < 2:
            return {"protected_class": protected_class, "status": "insufficient_data",
                    "reason": f"<2 identifiable {protected_class} groups with >= {_MIN_GROUP} "
                              "agency-passing loans", "data_source": ds,
                    "missing_inputs": [f"insufficient {protected_class} demographic diversity "
                                       "among agency-passing loans for overlay attribution"]}

        rates = {l: round(c["fail_overlay"] / c["pass_agency"], 4) for l, c in identifiable.items()}
        ref = min(rates, key=lambda k: rates[k])     # lowest overlay-fail rate = best
        ref_fail = rates[ref]
        ref_sel = 1.0 - ref_fail

        disparities = []
        for lbl, fr in rates.items():
            if lbl == ref:
                continue
            ratio = ((1.0 - fr) / ref_sel) if ref_sel > 0 else 0.0
            gap_pp = round((fr - ref_fail) * 100, 1)
            disparities.append({
                "group": lbl, "reference_group": ref,
                "overlay_fail_rate": fr, "ref_fail_rate": ref_fail,
                "four_fifths_ratio": round(ratio, 4), "gap_pp": gap_pp,
                "disparate_impact": (ratio < self._four_fifths) or (gap_pp > self._disparity_pp),
                "citation": "EEOC 29 CFR 1607.4(D) + internal overlay screen"})
        flagged = any(d["disparate_impact"] for d in disparities)
        return {"protected_class": protected_class,
                "status": "disparate_impact" if flagged else "clean",
                "overlay_fail_rates": rates, "reference_group": ref,
                "disparities": disparities, "has_disparate_impact": flagged,
                "data_source": ds, "missing_inputs": []}

    def analyze(self, loans: list, overlays: list, agency_floors: dict) -> dict:
        """loans: dicts with the gate fields + hmda demographics. overlays: rows with
        rule_type + overlay_value. agency_floors: {rule_type: agency value}."""
        loans = loans or []
        # strictest active overlay per simulatable rule_type
        by_type: dict = {}
        for ov in overlays or []:
            rt = ov.get("rule_type")
            if rt in SIMULATABLE_FIELDS:
                by_type.setdefault(rt, []).append(_num(ov.get("overlay_value")))

        results = []
        for rt, vals in by_type.items():
            field, _persona, direction = SIMULATABLE_FIELDS[rt]
            overlay_val = _strictest(vals, direction)
            agency = (agency_floors or {}).get(rt)
            if overlay_val is None or agency is None:
                results.append({"overlay": rt, "status": "not_applicable",
                                "reason": "missing overlay or agency floor value",
                                "data_source": "overlay_rules + agency_guidelines",
                                "missing_inputs": [f"{rt}: agency floor not resolved"]})
                continue
            class_results = {pc: self._analyze_overlay_class(loans, field, direction, agency,
                                                             overlay_val, pc)
                             for pc in ("race", "sex")}
            flagged = any(c.get("has_disparate_impact") for c in class_results.values())
            insufficient = all(c["status"] == "insufficient_data" for c in class_results.values())
            results.append({
                "overlay": rt, "gate_field": field, "direction": direction,
                "agency_floor": agency, "overlay_value": overlay_val,
                "status": ("disparate_impact" if flagged
                           else "insufficient_data" if insufficient else "clean"),
                "attribution": "loans that pass the agency floor but fail the stricter overlay",
                "by_class": class_results, "has_disparate_impact": flagged,
                "data_source": "entity_states (gate) + hmda_lar (demographics)",
                "missing_inputs": [m for c in class_results.values() for m in c.get("missing_inputs", [])]})

        flagged_overlays = [r["overlay"] for r in results if r.get("has_disparate_impact")]
        return {
            "status": ("disparity_detected" if flagged_overlays
                       else "insufficient_data" if results and all(
                           r["status"] in ("insufficient_data", "not_applicable") for r in results)
                       else "clean"),
            "overlays_analyzed": len(results), "flagged_overlays": flagged_overlays,
            "results": results,
            "thresholds": {"four_fifths_ratio": self._four_fifths,
                           "overlay_disparity_pp": self._disparity_pp,
                           "note": "4/5 ratio is the federal EEOC test; the pp gap is an "
                                   "internal screen (not a regulatory standard)"},
            "note": ("Attributes disparity to a specific lender overlay (loans that clear the "
                     "agency floor but fail the stricter overlay). Accord never uses "
                     "demographics in underwriting; this reads them post-decision only. A "
                     "flag requires review by qualified counsel."),
            "data_source": "overlay_rules + agency_guidelines + entity_states + hmda_lar",
            "missing_inputs": [m for r in results for m in r.get("missing_inputs", [])]}


async def load_agency_floors(conn, tenant_id: str) -> dict:
    """Resolve each overlay's agency floor from the catalogue (RULE 4), with a
    documented fallback (the values are the published Fannie guidelines)."""
    from core.catalogue.rule_loader import get_rule
    floors = {}
    for rt, (name, is_ceiling, fallback) in AGENCY_FLOOR_SPEC.items():
        try:
            r = await get_rule(conn, name, tenant_id, agency="fannie", is_ceiling=is_ceiling)
            ag = (r.get("layers") or {}).get("agency")
            floors[rt] = float(ag["value"]) if ag and ag.get("value") is not None else float(fallback)
        except Exception:
            floors[rt] = float(fallback)
    return floors


async def fetch_overlay_disparity_data(conn, tenant_id: str) -> tuple:
    """Loans (entity_states gate values ⋈ hmda_lar demographics) + active overlays +
    agency floors. Returns (loans, overlays, agency_floors)."""
    loans = await conn.fetch(
        "SELECT h.application_id, h.applicant_race, h.applicant_sex, "
        "       e.mid_credit_score, e.dti_back, e.ltv "
        "FROM hmda_lar h LEFT JOIN entity_states e "
        "  ON h.application_id=e.application_id AND h.tenant_id=e.tenant_id "
        "WHERE h.tenant_id=$1 ORDER BY h.application_id", tenant_id)
    overlays = await conn.fetch(
        "SELECT rule_type, overlay_value FROM overlay_rules "
        "WHERE tenant_id=$1 AND is_active=true", tenant_id)
    floors = await load_agency_floors(conn, tenant_id)
    return [dict(r) for r in loans], [dict(r) for r in overlays], floors


__all__ = ["OverlayDisparityAnalyzer", "load_agency_floors",
           "fetch_overlay_disparity_data", "AGENCY_FLOOR_SPEC"]
