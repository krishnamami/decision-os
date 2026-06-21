"""
Shared rule loader — core/catalogue/rule_loader.py

Resolvers read their thresholds from the catalogue tables (agency_guidelines,
platform_guardrails) instead of hardcoding dicts. This is the single place that
knows how to:

  * pull a rule by (agency, guideline_name) out of agency_guidelines,
  * parse the jsonb guideline_value into a plain scalar/list,
  * fall back to a SAFE_DEFAULT (and log a WARNING) when the catalogue is
    missing a rule — so a missing row degrades to a conservative default
    instead of crashing the pipeline or silently computing the wrong number.

Contract: a missing rule is never silently wrong. It either returns the
explicit `default` the caller passed, or a SAFE_DEFAULT, and always emits a
"CATALOGUE MISSING" WARNING so the gap shows up in logs.
"""

import logging

logger = logging.getLogger("catalogue.rule_loader")

# Conservative fallbacks, keyed by guideline_name. These mirror the seeded
# agency_guidelines rows (scripts/compliance/seed_agency_guidelines.py). If the
# catalogue is reachable these are never used; they exist so a missing row
# degrades safely.
SAFE_DEFAULTS = {
    # ── Asset (Fannie B3-4.3-04) ──
    "qualifying_factor_checking": 1.00,
    "qualifying_factor_savings": 1.00,
    "qualifying_factor_cd": 1.00,
    "qualifying_factor_retirement": 0.60,
    "qualifying_factor_stocks_bonds": 0.70,
    "qualifying_factor_crypto": 0.00,
    "minimum_reserves_months": 2,
    "large_deposit_threshold_pct": 50,
    "seasoning_days_required": 60,

    # ── Credit waiting periods (Fannie B3-5.3-07 / HUD 4000.1 / VA Ch.4) ──
    # Most conservative (longest) waiting period is the safe default.
    "bankruptcy_ch7_waiting_years": 4,
    "bankruptcy_ch13_waiting_years": 2,
    "foreclosure_waiting_years": 7,
    "short_sale_waiting_years": 4,
    "deed_in_lieu_waiting_years": 4,

    # ── Income ──
    "student_loan_deferred_rate_pct": 1.0,
    "medical_collection_excluded": True,
    "rental_vacancy_factor_pct": 25,
    "se_income_years_required": 2,
    "se_declining_use_lower_year": True,

    # ── Property ──
    "ineligible_property_types": ["vacant_land", "commercial", "cooperative"],
    "flood_zones_requiring_insurance": ["A", "AE", "AH", "AO", "V", "VE"],
    "condo_warrantability_required": True,
    "max_units_conventional": 4,

    # ── Platform risk thresholds (platform_guardrails, product_type=platform) ──
    "income_mismatch_medium_pct": 10,
    "income_mismatch_high_pct": 25,
    "income_mismatch_critical_pct": 50,
    "appraisal_gap_major_pct": 10,
    "appraisal_gap_minor_pct": 3,
    "undisclosed_debt_medium_mo": 200,
    "undisclosed_debt_high_mo": 500,
    "undisclosed_debt_critical_mo": 1000,
}


def _parse_gv(gv):
    """Parse an agency_guidelines.guideline_value jsonb into a plain scalar/list.

    The seeded shape is {"type": ..., "value": <scalar|list>, ...}. We return
    the inner ``value`` when present, otherwise the raw object (already a
    scalar/list/dict for non-wrapped rows).
    """
    if isinstance(gv, str):
        import json
        try:
            gv = json.loads(gv)
        except (ValueError, TypeError):
            return gv
    if isinstance(gv, dict):
        return gv.get("value", gv)
    return gv


async def get_rule(conn, agency, guideline_name, default=None):
    """Fetch a single rule value for (agency, guideline_name).

    Resolution order: catalogue row -> caller ``default`` -> SAFE_DEFAULTS ->
    None. Any fallback (i.e. the catalogue had no active row) logs a WARNING so
    the gap is visible.
    """
    row = await conn.fetchrow(
        """SELECT guideline_value FROM agency_guidelines
           WHERE agency = $1 AND guideline_name = $2 AND is_active = true
           ORDER BY effective_date DESC NULLS LAST LIMIT 1""",
        agency, guideline_name,
    )
    if row is not None:
        return _parse_gv(row["guideline_value"])

    if default is not None:
        fallback = default
    elif guideline_name in SAFE_DEFAULTS:
        fallback = SAFE_DEFAULTS[guideline_name]
    else:
        fallback = None
    logger.warning(
        "CATALOGUE MISSING agency=%s guideline=%s -> using fallback %r",
        agency, guideline_name, fallback,
    )
    return fallback


async def load_rules(conn, agency, category):
    """Load every rule for (agency, category) as {guideline_name: value}.

    The returned dict is guaranteed to contain every SAFE_DEFAULTS key (each
    missing one is coalesced and logged), plus any extra catalogue rows in the
    category that aren't in SAFE_DEFAULTS.
    """
    rows = await conn.fetch(
        """SELECT guideline_name, guideline_value FROM agency_guidelines
           WHERE agency = $1 AND category = $2 AND is_active = true""",
        agency, category,
    )
    rules = {r["guideline_name"]: _parse_gv(r["guideline_value"]) for r in rows}

    # Coalesce SAFE_DEFAULTS the catalogue didn't supply, logging each gap so a
    # missing row degrades safely instead of returning a hole the caller must
    # guard against.
    for name, value in SAFE_DEFAULTS.items():
        if name in rules:
            continue
        rules[name] = value
        logger.warning(
            "CATALOGUE MISSING agency=%s category=%s guideline=%s -> default %r",
            agency, category, name, value,
        )
    return rules


async def load_guardrails(conn):
    """Return platform_guardrails as {parameter: {"floor": x, "ceiling": y}}."""
    rows = await conn.fetch(
        "SELECT parameter, agency_floor, platform_ceiling FROM platform_guardrails")
    out = {}
    for r in rows:
        floor = r["agency_floor"]
        ceiling = r["platform_ceiling"]
        out[r["parameter"]] = {
            "floor": float(floor) if floor is not None else None,
            "ceiling": float(ceiling) if ceiling is not None else None,
        }
    return out


__all__ = [
    "SAFE_DEFAULTS",
    "get_rule",
    "load_rules",
    "load_guardrails",
]
