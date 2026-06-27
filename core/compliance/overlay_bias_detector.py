"""CM-G — proactive overlay proxy-discrimination risk detector.

Analyzes overlay RULES (structure), not loan OUTCOMES, for proxy-discrimination risk
— BEFORE/independent of demographic data. Complements CM-F (retrospective + demographic):
CM-G is the proactive structural screen that PROMPTS the CM-F demographic check.

Demographics-free: scores each overlay from (a) the criterion's known proxy
correlation (CFPB research weight), (b) severity vs the agency floor, and (c) the
fraction of agency-passing applicants the overlay excludes (entity_states). Produces
a REAL result even on meridian (where CM-D/CM-F return insufficient_data).

Sync + pure + RULE 11. Read-only -> 16/16 by construction.

DISCLAIMER: proxy-risk scores are INTERNAL screening heuristics, NOT legal findings
of discrimination. An elevated/high score -> document a business justification +
run the CM-F retrospective + fair-lending counsel review.
"""
from __future__ import annotations

from typing import Optional

RISK_LEVELS = ["low", "moderate", "elevated", "high"]

# Entity field + gate direction per overlay rule_type (mirrors CI-A's mapping).
OVERLAY_GATE_MAP = {
    "credit_floor": {"field": "mid_credit_score", "direction": "floor"},
    "dti_back_max": {"field": "dti_back", "direction": "ceiling"},
    "ltv_max_purchase": {"field": "ltv", "direction": "ceiling"},
}
# Severity normalization ranges per criterion (how big a deviation = "extreme").
_SEVERITY_RANGE = {"credit_floor": 200.0, "dti_back_max": 30.0, "ltv_max_purchase": 47.0}
# Default agency floors (catalogue values; overridden by the endpoint via the catalogue).
_DEFAULT_FLOORS = {
    "credit_floor": {"agency_value": 620, "direction": "floor"},
    "dti_back_max": {"agency_value": 50, "direction": "ceiling"},
    "ltv_max_purchase": {"agency_value": 97, "direction": "ceiling"},
}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class OverlayBiasDetector:
    DISCLAIMER = (
        "Proxy-risk scores are internal screening heuristics informed by CFPB supervisory "
        "research. They do NOT constitute a legal finding of discrimination. An elevated or "
        "high score requires: (1) a documented business justification for the overlay, "
        "(2) a CM-F retrospective demographic analysis, (3) fair-lending counsel review "
        "before the overlay remains in production.")

    def __init__(self, rules: Optional[dict] = None):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._weights = {
            "credit_floor": float(r.get("credit_floor_proxy_risk_weight", 0.70)),
            "dti_back_max": float(r.get("dti_proxy_risk_weight", 0.45)),
            "ltv_max_purchase": float(r.get("ltv_proxy_risk_weight", 0.35)),
        }
        self._elevated = float(r.get("overlay_bias_elevated_threshold", 0.55))
        self._high = float(r.get("overlay_bias_high_threshold", 0.75))

    def _risk_level(self, score: float) -> str:
        if score >= self._high:
            return "high"
        if score >= self._elevated:
            return "elevated"
        if score >= 0.30:
            return "moderate"
        return "low"

    def _severity_score(self, rule_type, overlay_value, agency_value, direction) -> float:
        if direction == "floor":
            gap = max(0.0, overlay_value - agency_value)
        else:
            gap = max(0.0, agency_value - overlay_value)
        return min(gap / _SEVERITY_RANGE.get(rule_type, 100.0), 1.0)

    def _exclusion_score(self, overlay_value, agency_value, direction, population) -> tuple:
        if not population:
            return 0.0, 0, 0
        ov, ag = float(overlay_value), float(agency_value)
        agency_passing = overlay_excluded = 0
        for val in population:
            v = _num(val)
            if v is None:
                continue
            if direction == "floor":
                if v >= ag:
                    agency_passing += 1
                    if v < ov:
                        overlay_excluded += 1
            else:
                if v <= ag:
                    agency_passing += 1
                    if v > ov:
                        overlay_excluded += 1
        excl_pct = round(overlay_excluded / agency_passing * 100, 1) if agency_passing else 0.0
        return excl_pct, overlay_excluded, agency_passing

    def score_overlay(self, rule_type, overlay_value, direction, agency_value, population) -> dict:
        criterion_weight = self._weights.get(rule_type, 0.40)
        severity = self._severity_score(rule_type, overlay_value, agency_value, direction)
        excl_pct, excl_n, agency_n = self._exclusion_score(
            overlay_value, agency_value, direction, population)
        exclusion_score = min(excl_pct / 100.0 * 2, 1.0)  # 50% excluded -> 1.0
        composite = round(min(criterion_weight * (0.5 * severity + 0.5 * exclusion_score), 1.0), 4)
        level = self._risk_level(composite)

        if level in ("elevated", "high"):
            rec = (f"REVIEW REQUIRED: {rule_type} ({overlay_value} vs agency {agency_value}) is "
                   f"{level} proxy risk; excludes ~{excl_pct}% of agency-passing applicants. "
                   "Actions: (1) document business justification, (2) run the CM-F demographic "
                   "retrospective, (3) consult fair-lending counsel.")
        elif level == "moderate":
            rec = (f"MONITOR: {rule_type} has moderate proxy risk — document the business "
                   "justification and review outcomes quarterly.")
        else:
            rec = f"Low proxy risk for {rule_type}. Continue standard fair-lending monitoring."

        missing = []
        if not population:
            missing.append(f"no entity_states population for {rule_type} — exclusion defaulted to 0")

        return {
            "rule_type": rule_type, "overlay_value": overlay_value, "agency_value": agency_value,
            "direction": direction, "risk_level": level, "composite_score": composite,
            "components": {"criterion_weight": criterion_weight,
                           "severity_score": round(severity, 4),
                           "exclusion_score": round(exclusion_score, 4),
                           "exclusion_pct": excl_pct, "overlay_excluded_n": excl_n,
                           "agency_passing_n": agency_n},
            "recommendation": rec,
            "citation": "CFPB Fair Lending Supervisory Research (internal heuristic)",
            "data_source": (f"overlay_rules.{rule_type} + agency_guidelines + "
                            f"entity_states.{OVERLAY_GATE_MAP.get(rule_type, {}).get('field', '')}"),
            "missing_inputs": missing,
        }

    def structural_scan(self, overlay_rules: list) -> dict:
        rule_types = {r.get("rule_type", "") for r in (overlay_rules or [])}
        findings = []
        geo = rule_types & {"zip_code", "county", "state", "geographic", "census_tract"}
        if geo:
            findings.append({"pattern": "geographic_variation", "risk": "high",
                             "rule_types": sorted(geo),
                             "note": "Geographic overlay rules carry the highest proxy risk (CFPB scrutiny)."})
        else:
            findings.append({"pattern": "geographic_variation", "risk": "low",
                             "note": "No geographic overlay rule_types — structural geographic-proxy risk is low."})
        if "min_loan_amount" in rule_types:
            findings.append({"pattern": "loan_size_minimum", "risk": "elevated",
                             "note": "A minimum loan amount excludes lower-value properties (LMI areas)."})
        if "property_type" in rule_types:
            findings.append({"pattern": "property_type_restriction", "risk": "moderate",
                             "note": "Property-type overlays may concentrate exclusion in minority areas."})
        return {"structural_findings": findings,
                "high_risk_patterns": sum(1 for f in findings if f["risk"] == "high"),
                "data_source": "overlay_rules.rule_type (structural)", "missing_inputs": []}

    def run(self, overlay_rules: list, population_data: dict,
            agency_floors: Optional[dict] = None) -> dict:
        floors = agency_floors or _DEFAULT_FLOORS
        # dedupe to the strictest overlay per rule_type
        by_type: dict = {}
        for rule in overlay_rules or []:
            rt = rule.get("rule_type", "")
            ov = _num(rule.get("overlay_value"))
            if rt not in floors or ov is None:
                continue
            d = floors[rt]["direction"]
            if rt not in by_type:
                by_type[rt] = rule
            else:
                cur = _num(by_type[rt].get("overlay_value")) or 0
                if (d == "floor" and ov > cur) or (d == "ceiling" and ov < cur):
                    by_type[rt] = rule

        results = []
        for rt, rule in by_type.items():
            meta = floors[rt]
            results.append(self.score_overlay(
                rt, _num(rule.get("overlay_value")), meta["direction"],
                float(meta["agency_value"]), population_data.get(rt, [])))

        structural = self.structural_scan(overlay_rules)
        return {
            "overlays_scored": len(results),
            "high_risk_count": sum(1 for r in results if r["risk_level"] == "high"),
            "elevated_risk_count": sum(1 for r in results if r["risk_level"] == "elevated"),
            "results": results, "structural_scan": structural, "disclaimer": self.DISCLAIMER,
            "data_source": "overlay_rules + agency_guidelines + entity_states (structural, no demographics)",
            "missing_inputs": sorted({m for r in results for m in r.get("missing_inputs", [])}),
        }


async def fetch_bias_detection_data(conn, tenant_id: str) -> tuple:
    """Fetch active overlays + the entity_states population per gate field."""
    overlays = await conn.fetch(
        "SELECT rule_type, overlay_value, direction, loan_type FROM overlay_rules "
        "WHERE tenant_id=$1 AND is_active=true", tenant_id)
    pop = await conn.fetch(
        "SELECT mid_credit_score, dti_back, ltv FROM entity_states WHERE tenant_id=$1", tenant_id)
    population = {
        "credit_floor": [r["mid_credit_score"] for r in pop if r["mid_credit_score"] is not None],
        "dti_back_max": [r["dti_back"] for r in pop if r["dti_back"] is not None],
        "ltv_max_purchase": [r["ltv"] for r in pop if r["ltv"] is not None],
    }
    return [dict(r) for r in overlays], population


__all__ = ["OverlayBiasDetector", "fetch_bias_detection_data", "OVERLAY_GATE_MAP", "RISK_LEVELS"]
